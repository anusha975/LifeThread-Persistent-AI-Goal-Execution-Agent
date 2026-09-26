output "bedrock_policy_arn" {
  value       = aws_iam_policy.bedrock_access.arn
  description = "IAM policy ARN granting Amazon Bedrock and Strands permissions"
}

output "strands_s3_bucket_name" {
  value       = aws_s3_bucket.strands.id
  description = "Name of the S3 bucket storing context strands"
}

output "strands_s3_bucket_arn" {
  value       = aws_s3_bucket.strands.arn
  description = "ARN of the S3 bucket storing context strands"
}
