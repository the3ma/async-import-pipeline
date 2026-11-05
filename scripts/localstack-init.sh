#!/bin/sh
# Runs inside LocalStack when it is ready: buckets, CORS, the event queue and expiry.
set -eu
awslocal s3 mb s3://entry
awslocal s3 mb s3://persistent
awslocal s3api put-bucket-cors --bucket entry --cors-configuration \
  '{"CORSRules":[{"AllowedOrigins":["http://localhost:8100","http://localhost:8101"],"AllowedMethods":["PUT"],"AllowedHeaders":["*"],"MaxAgeSeconds":3600}]}'
awslocal s3api put-bucket-lifecycle-configuration --bucket entry --lifecycle-configuration \
  '{"Rules":[{"ID":"expire-abandoned-uploads","Status":"Enabled","Filter":{"Prefix":""},"Expiration":{"Days":1}}]}'
queue_url=$(awslocal sqs create-queue --queue-name upload-events --query QueueUrl --output text)
queue_arn=$(awslocal sqs get-queue-attributes --queue-url "$queue_url" \
  --attribute-names QueueArn --query Attributes.QueueArn --output text)
awslocal s3api put-bucket-notification-configuration --bucket entry \
  --notification-configuration "{\"QueueConfigurations\":[{\"QueueArn\":\"$queue_arn\",\"Events\":[\"s3:ObjectCreated:*\"]}]}"
