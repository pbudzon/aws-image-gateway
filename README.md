# AWS Lambda Image Gateway

Image Gateway provides an API endpoint which creates resized versions of images stored inside an S3 bucket.

It uses a combination of S3 bucket, Lambda function, API Gateway and Cloudfront.

### Considerations:
- Lifecycle policy should be matched with CloudFront cache, as it is possible for CloudFront to redirect the user to a cached image after this image has been removed. Therefore it is advised that Maximum TTL for S3 origin should be set to 1209600 seconds (14 days).

## Lambda function environment:

- Pillow Python module is required 
- To create a ready to use package, you have to package the lambda source file (`lambda.py`) with the Pillow module. To do so, follow instructions here: [http://docs.aws.amazon.com/lambda/latest/dg/lambda-python-how-to-create-deployment-package.html](http://docs.aws.amazon.com/lambda/latest/dg/lambda-python-how-to-create-deployment-package.html)

## Creating CloudFormation stack:

1. Upload Lambda function ZIP (see above) into an S3 bucket.
1. Upload `infrastructure/templates/stack.json` into CloudFormation.
1. Fill out parameters:
  - `BucketName` - name of the bucket for storage that will be created
  - `LambdaSourceBucket` - name of the S3 bucket where you uploaded the Lambda function ZIP
  - `LambdaFileName` - name of the Lambda function ZIP file inside the above S3 bucket
1. Ta-dah! You'll find your CloudFront URL inside Outputs in CloudFormation.

### To update the Lambda function after creating the stack:
Lambda function is not updated by CloudFormation unless you change the parameters. So you can change the `LambdaSourceBucket` or `LambdaFileName` OR update
the Lambda manually:

- Get pre-compiled libraries (as above)
- Unzip the archive
- Copy `lambda.py` into the unpacked directory
- Zip the **contents** (not the directory) back.
- Upload to AWS Lambda or S3 bucket.

  
