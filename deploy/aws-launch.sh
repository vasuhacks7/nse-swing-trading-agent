#!/bin/bash
# Launch a new EC2 instance for the Trading Agent
# Run from your LOCAL machine with AWS CLI configured
#
# Usage: bash deploy/aws-launch.sh [region]
# Example: bash deploy/aws-launch.sh ap-south-1

set -euo pipefail

REGION="${1:-ap-south-1}"
INSTANCE_TYPE="t3.small"
AMI_FILTER="ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
KEY_NAME="trading-agent-key"
ROLE_NAME="TradingAgentRole"
SG_NAME="trading-agent-sg"
POLICY_NAME="TradingAgentBedrockPolicy"

echo "============================================"
echo "  AWS EC2 Launch — Trading Agent"
echo "  Region: $REGION"
echo "============================================"
echo ""

# --- 1. Create IAM Role ---
echo "[1/5] Creating IAM role: $ROLE_NAME..."
TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ec2.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

if aws iam get-role --role-name "$ROLE_NAME" --region "$REGION" &>/dev/null; then
    echo "  Role already exists."
else
    aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --region "$REGION" \
        --output text --query 'Role.Arn'

    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "$POLICY_NAME" \
        --policy-document file://deploy/iam-policy.json \
        --region "$REGION"

    echo "  Role created with Bedrock access."
fi

# Create instance profile
if ! aws iam get-instance-profile --instance-profile-name "$ROLE_NAME" &>/dev/null; then
    aws iam create-instance-profile --instance-profile-name "$ROLE_NAME" --region "$REGION"
    aws iam add-role-to-instance-profile \
        --instance-profile-name "$ROLE_NAME" \
        --role-name "$ROLE_NAME" \
        --region "$REGION"
    echo "  Waiting for instance profile propagation..."
    sleep 10
fi

# --- 2. Create Security Group ---
echo "[2/5] Creating security group: $SG_NAME..."
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" \
    --query 'Vpcs[0].VpcId' --output text --region "$REGION")

if aws ec2 describe-security-groups --group-names "$SG_NAME" --region "$REGION" &>/dev/null; then
    SG_ID=$(aws ec2 describe-security-groups --group-names "$SG_NAME" \
        --query 'SecurityGroups[0].GroupId' --output text --region "$REGION")
    echo "  Security group already exists: $SG_ID"
else
    SG_ID=$(aws ec2 create-security-group \
        --group-name "$SG_NAME" \
        --description "Trading Agent - HTTP/HTTPS/SSH" \
        --vpc-id "$VPC_ID" \
        --query 'GroupId' --output text --region "$REGION")

    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --region "$REGION" \
        --ip-permissions \
        "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=0.0.0.0/0,Description=SSH}]" \
        "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0,Description=HTTP}]" \
        "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0,Description=HTTPS}]"

    echo "  Created: $SG_ID (SSH + HTTP + HTTPS)"
fi

# --- 3. Create Key Pair ---
echo "[3/5] Setting up SSH key pair..."
if aws ec2 describe-key-pairs --key-names "$KEY_NAME" --region "$REGION" &>/dev/null; then
    echo "  Key pair '$KEY_NAME' already exists."
else
    aws ec2 create-key-pair \
        --key-name "$KEY_NAME" \
        --query 'KeyMaterial' --output text \
        --region "$REGION" > "${KEY_NAME}.pem"
    chmod 400 "${KEY_NAME}.pem"
    echo "  Created: ${KEY_NAME}.pem (save this file!)"
fi

# --- 4. Find latest Ubuntu AMI ---
echo "[4/5] Finding latest Ubuntu 22.04 AMI..."
AMI_ID=$(aws ec2 describe-images \
    --owners 099720109477 \
    --filters "Name=name,Values=$AMI_FILTER" "Name=state,Values=available" \
    --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
    --output text --region "$REGION")
echo "  AMI: $AMI_ID"

# --- 5. Launch Instance ---
echo "[5/5] Launching EC2 instance..."
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --iam-instance-profile "Name=$ROLE_NAME" \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]' \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=TradingAgent}]" \
    --query 'Instances[0].InstanceId' --output text \
    --region "$REGION")

echo "  Instance: $INSTANCE_ID"
echo "  Waiting for public IP..."

aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"

PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text --region "$REGION")

echo ""
echo "============================================"
echo "  EC2 Instance Ready!"
echo "============================================"
echo ""
echo "  Instance ID: $INSTANCE_ID"
echo "  Public IP:   $PUBLIC_IP"
echo "  Region:      $REGION"
echo ""
echo "Next steps:"
echo ""
echo "  1. SSH into the instance:"
echo "     ssh -i ${KEY_NAME}.pem ubuntu@${PUBLIC_IP}"
echo ""
echo "  2. Copy project files:"
echo "     scp -i ${KEY_NAME}.pem -r ./* ubuntu@${PUBLIC_IP}:/home/ubuntu/trading-agent/"
echo ""
echo "  3. Run setup on the instance:"
echo "     ssh -i ${KEY_NAME}.pem ubuntu@${PUBLIC_IP}"
echo "     cd /home/ubuntu/trading-agent"
echo "     bash deploy/setup.sh"
echo ""
echo "  4. Configure and start:"
echo "     cp .env.example .env"
echo "     nano .env  # Set AWS_REGION=$REGION, Telegram tokens"
echo "     sudo mv /home/ubuntu/trading-agent /opt/trading-agent"
echo "     cd /opt/trading-agent"
echo "     docker compose up -d --build"
echo ""
echo "  5. Open in browser: http://${PUBLIC_IP}"
echo ""
