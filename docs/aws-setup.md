# AWS setup for fast cloud renders (Remotion Lambda)

Goal: render a full 80 s episode at 1080×1920 in a few minutes by splitting it across many AWS Lambda workers.

## 1. AWS account
Sign in or sign up at https://aws.amazon.com/ and pick one region, **us-east-1** (N. Virginia).

## 2. Role for the render workers
1. Open IAM, go to **Roles**, and choose **Create role**.
2. Set Trusted entity to **AWS service**, use case **Lambda**, then choose **Next**.
3. Skip the permissions step for now, then choose **Next**.
4. Name it exactly **`remotion-lambda-role`** and create it.
5. Open the role, go to **Add permissions**, choose **Create inline policy**, then the **JSON** tab. Paste **Policy A** (below), then save it as `remotion-lambda-policy`.

## 3. User for this session
1. Open IAM, go to **Users**, and choose **Create user**. Name it `remotion-user`, with no console access.
2. Open the user, go to **Add permissions**, choose **Create inline policy**, then the **JSON** tab. Paste **Policy B** (below), then save it as `remotion-user-policy`.
3. Go to **Security credentials** and choose **Create access key**. For the use case, pick **Application running outside AWS**.
4. Keep the **Access key ID** and **Secret access key**, and don't paste them anywhere public.

## 4. Raise the Lambda limit
New AWS accounts can only run about 10 Lambdas at once, which is too few. Open **Service Quotas**, then **AWS Lambda**, then **Concurrent executions**, and request **1000** for us-east-1. Approval is usually quick.

## 5. Give the keys to this environment (you enter them, never in chat)
1. Open the cloud environment menu in the session title bar (environment **"pam"**) and choose **Edit**.
2. Under environment variables, add these three:
   - `REMOTION_AWS_ACCESS_KEY_ID` = your access key ID
   - `REMOTION_AWS_SECRET_ACCESS_KEY` = your secret access key
   - `REMOTION_AWS_REGION` = `us-east-1`
3. Start a new session, or resume this one, so the variables load. Then tell me "keys added".

## What I do next
1. Deploy the render function and the site bundle with `npx remotion lambda functions deploy` and `sites create`.
2. Render the full episode in the cloud and send you the MP4.

**Licensing:** Remotion is free for individuals and companies with up to 3 people; larger companies need a Remotion company licence.

**Cost:** Lambda for an 80 s episode is typically about $0.10–$0.50 per render, plus a few cents of S3 storage.

## Policy A — role `remotion-lambda-role` (inline policy)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "0",
      "Effect": "Allow",
      "Action": [
        "s3:ListAllMyBuckets"
      ],
      "Resource": [
        "*"
      ]
    },
    {
      "Sid": "1",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:ListBucket",
        "s3:PutBucketAcl",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:PutObjectAcl",
        "s3:PutObject",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::remotionlambda-*"
      ]
    },
    {
      "Sid": "2",
      "Effect": "Allow",
      "Action": [
        "lambda:InvokeFunction"
      ],
      "Resource": [
        "arn:aws:lambda:*:*:function:remotion-render-*"
      ]
    },
    {
      "Sid": "3",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup"
      ],
      "Resource": [
        "arn:aws:logs:*:*:log-group:/aws/lambda-insights"
      ]
    },
    {
      "Sid": "4",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": [
        "arn:aws:logs:*:*:log-group:/aws/lambda/remotion-render-*",
        "arn:aws:logs:*:*:log-group:/aws/lambda-insights:*"
      ]
    }
  ]
}

```

## Policy B — user `remotion-user` (inline policy)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "HandleQuotas",
      "Effect": "Allow",
      "Action": [
        "servicequotas:GetServiceQuota",
        "servicequotas:GetAWSDefaultServiceQuota",
        "servicequotas:RequestServiceQuotaIncrease",
        "servicequotas:ListRequestedServiceQuotaChangeHistoryByQuota"
      ],
      "Resource": [
        "*"
      ]
    },
    {
      "Sid": "PermissionValidation",
      "Effect": "Allow",
      "Action": [
        "iam:SimulatePrincipalPolicy"
      ],
      "Resource": [
        "*"
      ]
    },
    {
      "Sid": "LambdaInvokation",
      "Effect": "Allow",
      "Action": [
        "iam:PassRole"
      ],
      "Resource": [
        "arn:aws:iam::*:role/remotion-lambda-role"
      ]
    },
    {
      "Sid": "Storage",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:PutObjectAcl",
        "s3:PutObject",
        "s3:CreateBucket",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:PutBucketAcl",
        "s3:DeleteBucket",
        "s3:PutBucketOwnershipControls",
        "s3:PutBucketPublicAccessBlock",
        "s3:PutBucketPolicy",
        "s3:PutLifecycleConfiguration"
      ],
      "Resource": [
        "arn:aws:s3:::remotionlambda-*"
      ]
    },
    {
      "Sid": "BucketListing",
      "Effect": "Allow",
      "Action": [
        "s3:ListAllMyBuckets"
      ],
      "Resource": [
        "*"
      ]
    },
    {
      "Sid": "FunctionListing",
      "Effect": "Allow",
      "Action": [
        "lambda:ListFunctions",
        "lambda:GetFunction"
      ],
      "Resource": [
        "*"
      ]
    },
    {
      "Sid": "FunctionManagement",
      "Effect": "Allow",
      "Action": [
        "lambda:InvokeAsync",
        "lambda:InvokeFunction",
        "lambda:CreateFunction",
        "lambda:DeleteFunction",
        "lambda:PutFunctionEventInvokeConfig",
        "lambda:PutRuntimeManagementConfig",
        "lambda:TagResource"
      ],
      "Resource": [
        "arn:aws:lambda:*:*:function:remotion-render-*"
      ]
    },
    {
      "Sid": "LogsRetention",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:PutRetentionPolicy"
      ],
      "Resource": [
        "arn:aws:logs:*:*:log-group:/aws/lambda/remotion-render-*"
      ]
    },
    {
      "Sid": "FetchBinaries",
      "Effect": "Allow",
      "Action": [
        "lambda:GetLayerVersion"
      ],
      "Resource": [
        "arn:aws:lambda:*:678892195805:layer:remotion-binaries-*",
        "arn:aws:lambda:*:580247275435:layer:LambdaInsightsExtension*"
      ]
    }
  ]
}

```
