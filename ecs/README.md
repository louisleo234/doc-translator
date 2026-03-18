# ECS Fargate CDK Deployment Guide

Deploy the Doc Translation System to Amazon ECS Fargate using AWS CDK.

## Prerequisites

1. Node.js 18+ and npm
2. AWS CLI installed and configured
3. Docker installed and running
4. AWS CDK CLI (`npm install -g aws-cdk`)
5. AWS IAM user/role with permissions for ECS, ECR, VPC, ELB, IAM, CloudFormation, DynamoDB, S3, Bedrock
6. S3 bucket created for file storage
7. Bedrock model access enabled in your AWS account (Nova 2 Lite, Claude Sonnet/Haiku)

## Architecture

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                         VPC                              │
                    │  ┌─────────────────────────────────────────────────────┐ │
                    │  │                   Public Subnets                     │ │
Internet ──────────►│  │  ┌─────────────────────────────────────────────┐    │ │
                    │  │  │     Public Application Load Balancer        │    │ │
                    │  │  │   /:80 → Frontend    /api/*:80 → Backend    │    │ │
                    │  │  └─────────────────────────────────────────────┘    │ │
                    │  └─────────────────────────────────────────────────────┘ │
                    │  ┌─────────────────────────────────────────────────────┐ │
                    │  │                  Private Subnets                     │ │
                    │  │  ┌──────────────────┐    ┌──────────────────┐       │ │
                    │  │  │  ECS Service     │    │  ECS Service     │       │ │
                    │  │  │  (Frontend)      │    │  (Backend)       │       │ │
                    │  │  │  Nginx :8080     │    │  Uvicorn :8000   │       │ │
                    │  │  └──────────────────┘    └──────────────────┘       │ │
VPN / Direct ──────►│  │  ┌─────────────────────────────────────────────┐    │ │
Connect / Peering   │  │  │    Internal Application Load Balancer *     │    │ │
                    │  │  │   /:80 → Frontend    /api/*:80 → Backend    │    │ │
                    │  │  └─────────────────────────────────────────────┘    │ │
                    │  └─────────────────────────────────────────────────────┘ │
                    └─────────────────────────────────────────────────────────┘
                              * Optional: enabled with enableInternalAlb
                                                        │
                                              ┌─────────┼─────────┐
                                              ▼         ▼         ▼
                                          DynamoDB   Bedrock      S3
```

## Quick Start

```bash
cd ecs
npm install

# Set required environment variables
export AWS_REGION=your-region-code
export S3_BUCKET=your-s3-bucket-name
# Use: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
export JWT_SECRET=your-jwt-secret-key

# Create S3 bucket (if not already created)
aws s3 mb s3://$S3_BUCKET --region $AWS_REGION

# Bootstrap CDK (only required once per AWS account/region)
npx cdk bootstrap

# Deploy
npx cdk deploy
```

## Configuration

All parameters can be provided via CDK context (`-c key=value`) or environment variables. Context takes precedence.

### Required

| Parameter | Env Variable | Description |
|-----------|-------------|-------------|
| `s3Bucket` | `S3_BUCKET` | S3 bucket name for file storage |
| `jwtSecret` | `JWT_SECRET` | JWT signing secret |

### Optional

| Parameter | Env Variable | Default | Description |
|-----------|-------------|---------|-------------|
| `region` | `CDK_DEFAULT_REGION` | `us-west-2` | AWS region |
| `cpuArch` | `CPU_ARCH` | Auto-detected | CPU architecture: `arm64` or `x64` |
| `vpcCidr` | `VPC_CIDR` | `10.0.0.0/16` | VPC CIDR block |
| `albSourceCidr` | `ALB_SOURCE_CIDR` | `0.0.0.0/0` | Comma-separated CIDRs for public ALB access (ports 80/443) |
| `enableInternalAlb` | `ENABLE_INTERNAL_ALB` | `false` | Enable internal ALB for private access |
| `internalAlbSourceCidr` | `INTERNAL_ALB_SOURCE_CIDR` | VPC CIDR | Comma-separated CIDRs for internal ALB access (port 80) |
| - | `CDK_DEFAULT_ACCOUNT` | Auto-detected | AWS account ID |

## Networking

### Restricting Public ALB Access

By default, the internet-facing ALB allows traffic from any IP. Use `albSourceCidr` to restrict:

```bash
npx cdk deploy -c "albSourceCidr=203.0.113.0/24,198.51.100.0/24"
```

### Internal ALB

Enable the internal ALB for private access from within the VPC or connected networks (VPN, Direct Connect, VPC Peering, Transit Gateway) without traversing the public internet:

```bash
# Default: restricts to VPC CIDR
npx cdk deploy -c enableInternalAlb=true

# Restrict to specific CIDRs
npx cdk deploy -c enableInternalAlb=true -c internalAlbSourceCidr=172.16.0.0/12
```

When enabled, this creates:
- An internal ALB in private subnets with the same routing rules as the public ALB
- A security group allowing HTTP (port 80) from `internalAlbSourceCidr` (default: VPC CIDR)
- A CloudFormation output `InternalAlbDnsName` (only resolvable from within the VPC or connected networks)

### Custom VPC CIDR

Override the default VPC CIDR if it conflicts with your existing network:

```bash
npx cdk deploy -c vpcCidr=172.24.252.0/22
```

> **Note:** Changing `vpcCidr` on an existing stack replaces the VPC and all dependent resources. This is a destructive change — plan for downtime or deploy a new stack.

### Full Private-Access Example

```bash
npx cdk deploy \
  -c enableInternalAlb=true \
  -c vpcCidr=172.24.252.0/22 \
  -c "albSourceCidr=203.0.113.0/24" \
  -c "internalAlbSourceCidr=192.168.0.0/16,172.17.0.0/16,10.13.0.0/16"
```

## CDK Commands

```bash
npx cdk synth          # Generate CloudFormation template
npx cdk diff           # View change diff
npx cdk deploy         # Deploy stack
npx cdk destroy        # Delete all resources
```

## Post-Deployment

After deployment, CDK outputs the ALB DNS address:

```
Outputs:
DocTranslationStack.AlbDnsName = DocTr-Alb-xxxxx.us-west-2.elb.amazonaws.com
```

Query via CLI:

```bash
aws cloudformation describe-stacks \
  --stack-name DocTranslationStack \
  --query 'Stacks[0].Outputs[?OutputKey==`AlbDnsName`].OutputValue' \
  --output text
```

## Resource Details

### ECS Services

| Service | CPU | Memory | Port | Auto-scaling |
|---------|-----|--------|------|--------------|
| Backend | 1 vCPU | 2 GB | 8000 | 1-4 instances, CPU 70% |
| Frontend | 0.5 vCPU | 1 GB | 8080 | 1-4 instances, CPU 70% |

### Network

- VPC with 2 availability zones, configurable CIDR (default: `10.0.0.0/16`)
- Public subnets: public ALB
- Private subnets: ECS tasks (internet via NAT Gateway), internal ALB (if enabled)
- VPC Gateway Endpoints: S3, DynamoDB (no NAT charges)

### IAM Permissions

- **Execution role**: ECR image pull, CloudWatch log writes
- **Task role** (backend only): DynamoDB (`doc_translation_*` tables), Bedrock (InvokeModel/Converse), S3 (configured bucket)

### CloudFormation Outputs

| Output | Description |
|--------|-------------|
| `AlbDnsName` | Public ALB DNS address |
| `InternalAlbDnsName` | Internal ALB DNS address (when `enableInternalAlb` is true) |
| `ClusterName` | ECS cluster name |
| `BackendTaskDefinition` | Backend task definition ARN |
| `PrivateSubnets` | Private subnet ID list |
| `EcsSecurityGroup` | ECS security group ID |

## Troubleshooting

### View Service Logs

```bash
aws logs tail /ecs/doc-translation-backend --follow
aws logs tail /ecs/doc-translation-frontend --follow
```

### Check Task Status

```bash
aws ecs describe-services \
  --cluster doc-translation-cluster \
  --services DocTranslationStack-BackendService* \
  --query 'services[0].{status:status,running:runningCount,desired:desiredCount}'
```

### Common Issues

- **Task fails to start**: Check if Docker image built successfully, view CloudWatch logs
- **Health check fails**: Verify container port and health check path (Backend: `/api/health`, Frontend: `/`)
- **Bedrock calls fail**: Confirm model access is enabled in the target region

## Cost Estimation

| Resource | Configuration | Est. Monthly Cost |
|----------|--------------|-------------------|
| ECS Fargate (Backend) | 1 vCPU, 2 GB | ~$30 |
| ECS Fargate (Frontend) | 0.5 vCPU, 1 GB | ~$15 |
| ALB (public) | Base fee + LCU | ~$20 |
| ALB (internal, optional) | Base fee + LCU | ~$20 |
| NAT Gateway | 1 instance | ~$35 |
| DynamoDB | On-demand capacity | ~$5 |
| S3 | File storage | ~$1 |
| **Total** | | **~$106/month** |

*Actual costs depend on usage. Bedrock API costs are additional. Internal ALB adds ~$20/month when enabled.*

---

[Back to main README](../README.md)
