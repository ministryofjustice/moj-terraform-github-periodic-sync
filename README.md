# MoJ GitHub Periodic Sync

[![Standards Icon]][Standards Link] [![Format Code Icon]][Format Code Link] [![Scorecards Icon]][Scorecards Link] [![Test Icon]][Test Link] [![Terraform SCA Icon]][Terraform SCA Link]

Terraform module that deploys a scheduled AWS Lambda which keeps AWS IAM Identity Center (SSO) groups in step with GitHub team membership.

The poller reads the GitHub organisation [audit log](https://docs.github.com/en/organizations/keeping-your-organization-secure/managing-security-settings-for-your-organization/reviewing-the-audit-log-for-your-organization) on an EventBridge schedule (outbound-only; no inbound webhook), works out the delta for the teams that changed since the last run, and applies group creations and membership add/removes to the Identity Store. It is **dry-run by default** (`not_dry_run = false`) — set `not_dry_run = true` to enable writes once you have soaked it in shadow mode.

Deleting empty groups and orphaned users is intentionally out of scope; that is left to a separate reconciler.

## Usage

```hcl
module "github_periodic_sync" {
  source = "github.com/ministryofjustice/moj-terraform-github-periodic-sync?ref=v0.1.0"

  github_organisation   = "ministryofjustice"
  github_app_secret_arn = aws_secretsmanager_secret.github_periodic_sync.arn
  cursor_parameter_name = aws_ssm_parameter.github_periodic_sync_audit_cursor.name

  sso_aws_region        = "eu-west-2"
  sso_identity_store_id = "d-1234567890"
  sso_email_suffix      = "@digital.justice.gov.uk"

  not_dry_run = false

  tags = local.tags
}
```

The GitHub App credentials are supplied out-of-band as a Secrets Manager secret containing JSON `{ "app_id": "...", "installation_id": "...", "private_key": "..." }`. The audit-log cursor SSM parameter is created outside this module (e.g. in `aws-root-account`) and passed in via `curŸsor_parameter_name`.

## Looking for issues?

If you're looking to raise an issue with this module, please create a new issue in the [module repository](https://github.com/ministryofjustice/moj-terraform-github-periodic-sync/issues).

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | ~> 1.0 |
| <a name="requirement_archive"></a> [archive](#requirement\_archive) | >= 2.4.0 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | ~> 6.0 |
| <a name="requirement_external"></a> [external](#requirement\_external) | >= 2.3.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_archive"></a> [archive](#provider\_archive) | 2.8.0 |
| <a name="provider_aws"></a> [aws](#provider\_aws) | 6.52.0 |
| <a name="provider_external"></a> [external](#provider\_external) | 2.4.0 |

## Modules

No modules.

## Resources

| Name | Type |
|------|------|
| [aws_cloudwatch_event_rule.default](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_target.default](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_cloudwatch_log_group.default](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_iam_policy.default](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_policy) | resource |
| [aws_iam_role.default](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy_attachment.default](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_lambda_function.default](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_function) | resource |
| [aws_lambda_permission.default](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_permission) | resource |
| [archive_file.function](https://registry.terraform.io/providers/hashicorp/archive/latest/docs/data-sources/file) | data source |
| [aws_caller_identity.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/caller_identity) | data source |
| [aws_iam_policy_document.assume_role](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.default](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_kms_alias.lambda](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/kms_alias) | data source |
| [external_external.build](https://registry.terraform.io/providers/hashicorp/external/latest/docs/data-sources/external) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_cursor_parameter_name"></a> [cursor\_parameter\_name](#input\_cursor\_parameter\_name) | Name of the SSM parameter holding the audit-log cursor. Created outside this module (e.g. in aws-root-account); the Lambda reads/writes it. | `string` | n/a | yes |
| <a name="input_github_app_secret_arn"></a> [github\_app\_secret\_arn](#input\_github\_app\_secret\_arn) | ARN of the Secrets Manager secret holding JSON {app\_id, installation\_id, private\_key} for the GitHub App. | `string` | n/a | yes |
| <a name="input_github_organisation"></a> [github\_organisation](#input\_github\_organisation) | GitHub organisation to poll. | `string` | n/a | yes |
| <a name="input_lambda_memory"></a> [lambda\_memory](#input\_lambda\_memory) | Lambda memory (MB). | `number` | `256` | no |
| <a name="input_lambda_timeout"></a> [lambda\_timeout](#input\_lambda\_timeout) | Lambda timeout (seconds). | `number` | `120` | no |
| <a name="input_log_retention_days"></a> [log\_retention\_days](#input\_log\_retention\_days) | CloudWatch log retention for the poller. | `number` | `30` | no |
| <a name="input_lookback_minutes"></a> [lookback\_minutes](#input\_lookback\_minutes) | On the very first run (no cursor yet) how far back to read the audit log. | `number` | `60` | no |
| <a name="input_max_changes_per_run"></a> [max\_changes\_per\_run](#input\_max\_changes\_per\_run) | Blast-radius cap: abort a live run that would make more than this many changes. | `number` | `50` | no |
| <a name="input_name"></a> [name](#input\_name) | Name used for the Lambda, role, log group and cursor parameter. | `string` | `"moj-github-periodic-sync"` | no |
| <a name="input_not_dry_run"></a> [not\_dry\_run](#input\_not\_dry\_run) | When true the poller performs writes. Defaults to false (shadow mode: log only). | `bool` | `false` | no |
| <a name="input_schedule_expression"></a> [schedule\_expression](#input\_schedule\_expression) | EventBridge schedule for the poll. SLA is 30 min; 10 min gives headroom. | `string` | `"rate(10 minutes)"` | no |
| <a name="input_sso_aws_region"></a> [sso\_aws\_region](#input\_sso\_aws\_region) | Region the IAM Identity Center instance is in. | `string` | n/a | yes |
| <a name="input_sso_email_suffix"></a> [sso\_email\_suffix](#input\_sso\_email\_suffix) | Suffix stripped from Identity Store UserName to derive the GitHub login (e.g. @example.com). | `string` | `"@digital.justice.gov.uk"` | no |
| <a name="input_sso_identity_store_id"></a> [sso\_identity\_store\_id](#input\_sso\_identity\_store\_id) | Identity Store id. Leave empty to discover via sso:ListInstances at runtime. | `string` | `""` | no |
| <a name="input_tags"></a> [tags](#input\_tags) | Tags applied to resources, where applicable. | `map(string)` | `{}` | no |
| <a name="input_v1_lambda_name"></a> [v1\_lambda\_name](#input\_v1\_lambda\_name) | Name of the v1 Lambda. On first run the window is seeded from its last execution time (CloudWatch Logs) to avoid a cutover gap. Empty disables this. | `string` | `"aws-sso-scim-github"` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_cursor_parameter_name"></a> [cursor\_parameter\_name](#output\_cursor\_parameter\_name) | SSM parameter holding the audit-log cursor (created outside this module). |
| <a name="output_lambda_function_arn"></a> [lambda\_function\_arn](#output\_lambda\_function\_arn) | ARN of the poller Lambda function. |
| <a name="output_lambda_function_name"></a> [lambda\_function\_name](#output\_lambda\_function\_name) | Name of the poller Lambda function. |
| <a name="output_lambda_role_arn"></a> [lambda\_role\_arn](#output\_lambda\_role\_arn) | Execution role ARN of the poller Lambda. |
| <a name="output_schedule_rule_name"></a> [schedule\_rule\_name](#output\_schedule\_rule\_name) | EventBridge rule that triggers the poller. |
<!-- END_TF_DOCS -->

[Standards Link]: https://github-community.service.justice.gov.uk/repository-standards/moj-terraform-github-periodic-sync "Repo standards badge."
[Standards Icon]: https://github-community.service.justice.gov.uk/repository-standards/api/moj-terraform-github-periodic-sync/badge
[Format Code Icon]: https://img.shields.io/github/actions/workflow/status/ministryofjustice/moj-terraform-github-periodic-sync/format-code.yml?labelColor=231f20&style=for-the-badge&label=Format%20Code
[Format Code Link]: https://github.com/ministryofjustice/moj-terraform-github-periodic-sync/actions/workflows/format-code.yml
[Scorecards Icon]: https://img.shields.io/github/actions/workflow/status/ministryofjustice/moj-terraform-github-periodic-sync/scorecards.yml?branch=main&labelColor=231f20&style=for-the-badge&label=Scorecards
[Scorecards Link]: https://github.com/ministryofjustice/moj-terraform-github-periodic-sync/actions/workflows/scorecards.yml
[Test Icon]: https://img.shields.io/github/actions/workflow/status/ministryofjustice/moj-terraform-github-periodic-sync/test.yml?branch=main&labelColor=231f20&style=for-the-badge&label=Unit%20Tests
[Test Link]: https://github.com/ministryofjustice/moj-terraform-github-periodic-sync/actions/workflows/test.yml
[Terraform SCA Icon]: https://img.shields.io/github/actions/workflow/status/ministryofjustice/moj-terraform-github-periodic-sync/terraform-static-analysis.yml?branch=main&labelColor=231f20&style=for-the-badge&label=Terraform%20Static%20Code%20Analysis
[Terraform SCA Link]: https://github.com/ministryofjustice/moj-terraform-github-periodic-sync/actions/workflows/terraform-static-analysis.yml
