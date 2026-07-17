output "lambda_function_name" {
  description = "Name of the poller Lambda function."
  value       = aws_lambda_function.default.function_name
}

output "lambda_function_arn" {
  description = "ARN of the poller Lambda function."
  value       = aws_lambda_function.default.arn
}

output "lambda_role_arn" {
  description = "Execution role ARN of the poller Lambda."
  value       = aws_iam_role.default.arn
}

output "cursor_parameter_name" {
  description = "SSM parameter holding the audit-log cursor (created outside this module)."
  value       = var.cursor_parameter_name
}

output "schedule_rule_name" {
  description = "EventBridge rule that triggers the poller."
  value       = aws_cloudwatch_event_rule.default.name
}
