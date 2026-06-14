# Secrets Manager CONTAINERS for the credentials a deployment needs. These
# define the secrets' existence and access policy only — NO secret values are
# set here. A deployment injects the actual values out-of-band (e.g. via the
# AWS console, CI with OIDC, or `aws secretsmanager put-secret-value`), so no
# credential ever lives in Terraform state or the repo.
#
# Expected JSON shape (documented, not stored):
#   snowflake → {account, user, private_key, warehouse, database, schema}
#   anthropic → {api_key}

resource "aws_secretsmanager_secret" "snowflake" {
  name        = "${local.name}/snowflake"
  description = "Snowflake key-pair credentials for EDGAR-X (value injected out-of-band)."
  tags        = local.tags
}

resource "aws_secretsmanager_secret" "anthropic" {
  name        = "${local.name}/anthropic"
  description = "Anthropic API key for EDGAR-X agents (value injected out-of-band)."
  tags        = local.tags
}
