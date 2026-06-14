# Outputs a deployment would consume (kubeconfig wiring, image pushes, IRSA).

output "cluster_name" {
  description = "EKS cluster name."
  value       = aws_eks_cluster.main.name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = aws_eks_cluster.main.endpoint
}

output "cluster_oidc_provider_arn" {
  description = "OIDC provider ARN for IRSA service-account bindings."
  value       = aws_iam_openid_connect_provider.eks.arn
}

output "app_secrets_role_arn" {
  description = "IRSA role ARN the app service account annotates to read secrets."
  value       = aws_iam_role.app_secrets.arn
}

output "ecr_repository_urls" {
  description = "ECR repository URLs, keyed by service."
  value       = { for k, repo in aws_ecr_repository.service : k => repo.repository_url }
}

output "vpc_id" {
  description = "VPC id."
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Private subnet ids (worker nodes)."
  value       = aws_subnet.private[*].id
}
