data "aws_caller_identity" "current" {}

locals {
  name             = var.name
  cursor_param_arn = "arn:aws:ssm:${var.sso_aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.cursor_parameter_name}"
}

# KMS alias used to encrypt the Lambda environment.
data "aws_kms_alias" "lambda" {
  name = "alias/aws/lambda"
}

# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "default" {
  name               = "${local.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = var.tags
}

data "aws_iam_policy_document" "default" {
  # Write logs.
  statement {
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.default.arn}:*"]
  }

  # Read the GitHub App secret (JSON: app_id, installation_id, private_key).
  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.github_app_secret_arn]
  }

  # Read the v1 Lambda's log streams to seed the first-run window (bootstrap).
  statement {
    effect    = "Allow"
    actions   = ["logs:DescribeLogStreams"]
    resources = ["arn:aws:logs:${var.sso_aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.v1_lambda_name}:*"]
  }

  # Read + write only the cursor parameter.
  statement {
    effect    = "Allow"
    actions   = ["ssm:GetParameter", "ssm:PutParameter"]
    resources = [local.cursor_param_arn]
  }

  # Discover the Identity Store instance when sso_identity_store_id is empty.
  statement {
    effect    = "Allow"
    actions   = ["sso:ListInstances"]
    resources = ["*"]
  }

  # Identity Store reads + the three permitted writes (no group/user deletion;
  # destructive cleanup is the nightly reconciler's job).
  statement {
    effect = "Allow"
    actions = [
      "identitystore:ListGroups",
      "identitystore:ListUsers",
      "identitystore:ListGroupMemberships",
      "identitystore:GetGroupId",
      "identitystore:GetGroupMembershipId",
      "identitystore:CreateGroup",
      "identitystore:CreateGroupMembership",
      "identitystore:DeleteGroupMembership",
    ]
    resources = [
      "arn:aws:identitystore::${data.aws_caller_identity.current.account_id}:identitystore/${var.sso_identity_store_id}",
      "arn:aws:identitystore:::user/*",
      "arn:aws:identitystore:::group/*",
      "arn:aws:identitystore:::membership/*",
    ]
  }
}

resource "aws_iam_policy" "default" {
  name   = local.name
  policy = data.aws_iam_policy_document.default.json
  tags   = var.tags
}

resource "aws_iam_role_policy_attachment" "default" {
  role       = aws_iam_role.default.name
  policy_arn = aws_iam_policy.default.arn
}

# ---------------------------------------------------------------------------
# CloudWatch Logs + schedule
# ---------------------------------------------------------------------------
#trivy:ignore:AVD-AWS-0017
resource "aws_cloudwatch_log_group" "default" {
  #checkov:skip=CKV_AWS_338:30 day retention is sufficient for these logs
  #checkov:skip=CKV_AWS_158:CloudWatch Logs KMS encryption not required for this use case
  name              = "/aws/lambda/${local.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_event_rule" "default" {
  name                = "run-${local.name}"
  description         = "Scheduled audit-log poll for ${local.name}"
  schedule_expression = var.schedule_expression
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "default" {
  rule = aws_cloudwatch_event_rule.default.name
  arn  = aws_lambda_function.default.arn
}

resource "aws_lambda_permission" "default" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.default.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.default.arn
}

# ---------------------------------------------------------------------------
# Build + package the Lambda (self-building, like v1's npm/zip flow).
# ---------------------------------------------------------------------------
data "external" "build" {
  program     = ["bash", "${path.module}/build.sh"]
  working_dir = path.module
}

data "archive_file" "function" {
  type        = "zip"
  output_path = "${path.module}/function.zip"
  source_dir  = "${path.module}/${data.external.build.result.build_dir}"
  depends_on  = [data.external.build]
}

#trivy:ignore:AVD-AWS-0066
resource "aws_lambda_function" "default" {
  #checkov:skip=CKV_AWS_117:No VPC access required for this use case
  #checkov:skip=CKV_AWS_116:DLQ not required for an idempotent scheduled poll
  #checkov:skip=CKV_AWS_272:Code signing not implemented
  #checkov:skip=CKV_AWS_115:Reserved concurrency not required for a single scheduled invocation
  #checkov:skip=CKV_AWS_50:X-Ray not required; CloudWatch Logs/metrics suffice
  filename         = data.archive_file.function.output_path
  function_name    = local.name
  handler          = "scim_sync.handlers.poller.handler"
  kms_key_arn      = data.aws_kms_alias.lambda.target_key_arn
  role             = aws_iam_role.default.arn
  runtime          = "python3.13"
  source_code_hash = data.archive_file.function.output_base64sha256
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory
  architectures    = ["arm64"]

  environment {
    variables = {
      GITHUB_ORG             = var.github_organisation
      GITHUB_APP_SECRET      = var.github_app_secret_arn
      SSO_IDENTITY_STORE_ID  = var.sso_identity_store_id
      SSO_EMAIL_SUFFIX       = var.sso_email_suffix
      AUDIT_CURSOR_PARAMETER = var.cursor_parameter_name
      LOOKBACK_MINUTES       = tostring(var.lookback_minutes)
      V1_LAMBDA_NAME         = var.v1_lambda_name
      NOT_DRY_RUN            = var.not_dry_run ? "true" : "false"
      MAX_CHANGES_PER_RUN    = tostring(var.max_changes_per_run)
    }
  }

  tags = var.tags

  depends_on = [
    data.archive_file.function,
    aws_cloudwatch_log_group.default,
  ]
}
