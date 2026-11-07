#!/usr/bin/env bash
# Run ONCE with an admin profile of the NEW account (never root access keys).
# Creates a least-privilege IAM user that can only call Amazon Nova Pro on Bedrock,
# and stores its access key in a local AWS CLI profile named "nova-copilot".
set -euo pipefail
ADMIN_PROFILE="${ADMIN_PROFILE:?set ADMIN_PROFILE to the new account admin profile}"
USER_NAME="nova-copilot-dev"
POLICY_NAME="NovaCopilotInvokeNovaPro"
HERE="$(cd "$(dirname "$0")" && pwd)"

aws iam create-user --user-name "$USER_NAME" --profile "$ADMIN_PROFILE" >/dev/null
aws iam put-user-policy --user-name "$USER_NAME" --policy-name "$POLICY_NAME" \
  --policy-document "file://$HERE/nova-copilot-invoke-policy.json" --profile "$ADMIN_PROFILE"

read -r KEY_ID SECRET < <(aws iam create-access-key --user-name "$USER_NAME" \
  --profile "$ADMIN_PROFILE" --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)
aws configure set aws_access_key_id "$KEY_ID" --profile nova-copilot
aws configure set aws_secret_access_key "$SECRET" --profile nova-copilot
aws configure set region us-east-1 --profile nova-copilot
unset KEY_ID SECRET
echo "Profile nova-copilot configured. Test with:"
echo "  AWS_PROFILE=nova-copilot python3 chat.py \"Which sessions should I take on agents?\""
