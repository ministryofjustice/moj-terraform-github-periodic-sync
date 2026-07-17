variable "name" {
  type        = string
  description = "Name used for the Lambda, role, log group and cursor parameter."
  default     = "moj-github-periodic-sync"
}

variable "github_organisation" {
  type        = string
  description = "GitHub organisation to poll."
}

variable "github_app_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret holding JSON {app_id, installation_id, private_key} for the GitHub App."
}

variable "cursor_parameter_name" {
  type        = string
  description = "Name of the SSM parameter holding the audit-log cursor. Created outside this module (e.g. in aws-root-account); the Lambda reads/writes it."
}

variable "sso_aws_region" {
  type        = string
  description = "Region the IAM Identity Center instance is in."
}

variable "sso_identity_store_id" {
  type        = string
  description = "Identity Store id. Leave empty to discover via sso:ListInstances at runtime."
  default     = ""
}

variable "sso_email_suffix" {
  type        = string
  description = "Suffix stripped from Identity Store UserName to derive the GitHub login (e.g. @example.com)."
  default     = "@digital.justice.gov.uk"
}

variable "not_dry_run" {
  type        = bool
  description = "When true the poller performs writes. Defaults to false (shadow mode: log only)."
  default     = false
}

variable "max_changes_per_run" {
  type        = number
  description = "Blast-radius cap: abort a live run that would make more than this many changes."
  default     = 50
}

variable "schedule_expression" {
  type        = string
  description = "EventBridge schedule for the poll. SLA is 30 min; 10 min gives headroom."
  default     = "rate(10 minutes)"
}

variable "lookback_minutes" {
  type        = number
  description = "On the very first run (no cursor yet) how far back to read the audit log."
  default     = 60
}

variable "v1_lambda_name" {
  type        = string
  description = "Name of the v1 Lambda. On first run the window is seeded from its last execution time (CloudWatch Logs) to avoid a cutover gap. Empty disables this."
  default     = "aws-sso-scim-github"
}

variable "lambda_timeout" {
  type        = number
  description = "Lambda timeout (seconds)."
  default     = 120
}

variable "lambda_memory" {
  type        = number
  description = "Lambda memory (MB)."
  default     = 256
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention for the poller."
  default     = 30
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to resources, where applicable."
  default     = {}
}
