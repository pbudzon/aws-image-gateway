from troposphere import GetAtt, Ref, Template, Output, Parameter, Join
from troposphere import s3
from troposphere import iam
from troposphere import awslambda
from troposphere import cloudfront
from troposphere import apigateway
from awacs import aws, sts

template = Template()

template.add_description("Image gateway")

template.add_metadata({
    'AWS::CloudFormation::Interface': {
        'ParameterGroups': [
            {
                'Label': {'default': 'Storage'},
                'Parameters': ['BucketName']
            },
            {
                'Label': {'default': 'Lambda source'},
                'Parameters': ['LambdaSourceBucket', 'LambdaFileName']
            },
        ],
        'ParameterLabels': {
            'BucketName': {'default': 'S3 Storage Bucket'},
            'LambdaSourceBucket': {'default': 'S3 Bucket with Lambda source'},
            'LambdaFileName': {'default': 'Path and name of the file inside S3 Bucket'},
        }
    }
})

param_bucket_name = template.add_parameter(Parameter(
    "BucketName",
    Type="String",
    Description='Name of the STORAGE bucket to create where the images will be uploaded and renditions cached'
))

param_lambda_source_bucket = template.add_parameter(Parameter(
    "LambdaSourceBucket",
    Type="String",
    Description="Name of the bucket where lambda function sources is stored"
))

param_lambda_file_name = template.add_parameter(Parameter(
    "LambdaFileName",
    Type="String",
    Description="Name of the ZIP file with lambda function sources inside LambdaSourceBucket"
))

bucket = template.add_resource(s3.Bucket(
    "StorageBucket",
    AccessControl='Private',
    BucketName=Ref(param_bucket_name),
    LifecycleConfiguration=s3.LifecycleConfiguration(
        Rules=[
            s3.LifecycleRule(
                Prefix="images/",
                Status="Enabled",
                ExpirationInDays=14
            )
        ]
    ),
    WebsiteConfiguration=s3.WebsiteConfiguration(
        IndexDocument="index.html"
    )
))

lambda_role = template.add_resource(iam.Role(
    "LambaRole",
    AssumeRolePolicyDocument=aws.Policy(
        Statement=[
            aws.Statement(
                Effect=aws.Allow,
                Action=[sts.AssumeRole],
                Principal=aws.Principal(
                    "Service", ["lambda.amazonaws.com"]
                )
            )
        ]
    ),
    Policies=[
        iam.Policy(
            PolicyName="ImgGatewayLambaPolicy",
            PolicyDocument=aws.Policy(
                Statement=[
                    aws.Statement(
                        Effect=aws.Allow,
                        Action=[
                            aws.Action("logs", "CreateLogGroup"),
                            aws.Action("logs", "CreateLogStream"),
                            aws.Action("logs", "PutLogEvents"),
                        ],
                        Resource=["arn:aws:logs:*:*:*"]
                    ),
                    aws.Statement(
                        Effect=aws.Allow,
                        Action=[
                            aws.Action("s3", "GetObject")
                        ],
                        Resource=[
                            Join("", ["arn:aws:s3:::", Ref(bucket), "/*"])
                        ]
                    ),
                    aws.Statement(
                        Effect=aws.Allow,
                        Action=[
                            aws.Action("s3", "PutObject*")
                        ],
                        Resource=[
                            Join("", ["arn:aws:s3:::", Ref(bucket), "/images/*"])
                        ]
                    )
                ]
            )

        )
    ]
))

lambda_function = template.add_resource(awslambda.Function(
    "Lambda",
    Code=awslambda.Code(
        S3Bucket=Ref(param_lambda_source_bucket),
        S3Key=Ref(param_lambda_file_name)
    ),
    Handler="lambda.lambda_handler",
    MemorySize=128,
    Role=GetAtt(lambda_role, "Arn"),
    Runtime="python2.7",
    Timeout=30
))

api = template.add_resource(apigateway.RestApi(
    "API",
    Description="Image Gateway API",
    Name="ImageGateway"
))

cloudfront_distro = template.add_resource(cloudfront.Distribution(
    "CloudFrontDistribution",
    DistributionConfig=cloudfront.DistributionConfig(
        Comment="Image Gateway",
        Enabled=True,
        DefaultCacheBehavior=cloudfront.DefaultCacheBehavior(
            ForwardedValues=cloudfront.ForwardedValues(
                QueryString=True,
                Headers=["Location"]
            ),
            TargetOriginId="lambda",
            ViewerProtocolPolicy="allow-all"
        ),
        CacheBehaviors=[
            cloudfront.CacheBehavior(
                TargetOriginId="bucket",
                DefaultTTL=86400,
                PathPattern="images/*",
                ForwardedValues=cloudfront.ForwardedValues(
                    QueryString=False,
                ),
                ViewerProtocolPolicy="allow-all"
            )
        ],
        Origins=[
            {
                "CustomOriginConfig": cloudfront.CustomOrigin(
                    OriginProtocolPolicy="https-only"
                ),
                "DomainName": Join("", [Ref(api), ".execute-api.", Ref("AWS::Region"), ".amazonaws.com"]),
                "OriginPath": "/live",
                "Id": "lambda"
            },
            {
                "CustomOriginConfig": cloudfront.CustomOrigin(
                    OriginProtocolPolicy="http-only"
                ),
                "DomainName": Join("", [Ref(bucket), ".s3-website-", Ref("AWS::Region"), ".amazonaws.com"]),
                "Id": "bucket"
            }

        ],
        PriceClass='PriceClass_100',
        CustomErrorResponses=[
            cloudfront.CustomErrorResponse(
                ErrorCode=403,
                ErrorCachingMinTTL=0
            ),
            cloudfront.CustomErrorResponse(
                ErrorCode=404,
                ErrorCachingMinTTL=0
            )
        ]
    )
))

api_image_resource = template.add_resource(apigateway.Resource(
    "APIImageResource",
    ParentId=GetAtt(api, "RootResourceId"),
    PathPart="{image}",
    RestApiId=Ref(api)
))

api_image_method = template.add_resource(apigateway.Method(
    "APIImageMethodGET",
    ApiKeyRequired=False,
    AuthorizationType="NONE",
    HttpMethod="GET",
    ResourceId=Ref(api_image_resource),
    RestApiId=Ref(api),
    Integration=apigateway.Integration(
        Type="AWS",
        IntegrationHttpMethod="POST",
        Uri=Join("", [
            "arn:aws:apigateway:",
            Ref("AWS::Region"),
            ":lambda:path/2015-03-31/functions/",
            GetAtt(lambda_function, "Arn"),
            "/invocations"
        ]),
        RequestTemplates={
            "application/json": Join("", [
                "{\"width\": \"$input.params('width')\", \"image\": \"$input.params('image')\", \"height\": \"$input.params('height')\", \"bucket\":\"",
                Ref(param_bucket_name),
                "\", \"cloudfront\":\"", GetAtt(cloudfront_distro, "DomainName"), "\"}"
            ])
        },
        IntegrationResponses=[
            apigateway.IntegrationResponse(
                "IntegrationResponse",
                StatusCode="302",
                ResponseParameters={
                    "method.response.header.Location": "integration.response.body.location"
                },
                ResponseTemplates={
                    "application/json": "$input.params('whatever')"
                }
            ),
            apigateway.IntegrationResponse(
                "IntegrationResponse",
                StatusCode="404",
                SelectionPattern="[a-zA-Z]+.*",  # any error
                ResponseTemplates={
                    "application/json": "$input.params('whatever')"
                }
            ),
        ]
    ),
    RequestParameters={
        "method.request.path.image": True,
        "method.request.querystring.height": True,
        "method.request.querystring.width": True,
    },
    MethodResponses=[
        apigateway.MethodResponse(
            "APIResponse",
            StatusCode="302",
            ResponseParameters={
                "method.response.header.Location": True
            }
        ),
        apigateway.MethodResponse(
            "APIResponse",
            StatusCode="404"
        )
    ]
))

api_lambda_permission = template.add_resource(awslambda.Permission(
    "APILambdaPermission",
    Action="lambda:InvokeFunction",
    FunctionName=Ref(lambda_function),
    Principal="apigateway.amazonaws.com",
    SourceArn=Join("", [
        "arn:aws:execute-api:",
        Ref("AWS::Region"),
        ":",
        Ref("AWS::AccountId"),
        ":",
        Ref(api),
        "/*/GET/*"
    ])
))

api_deployment = template.add_resource(apigateway.Deployment(
    "APIDeployment",
    RestApiId=Ref(api),
    StageName="live",
    StageDescription=apigateway.StageDescription(
        CacheClusterEnabled=False,
    )
))

template.add_output(Output(
    "CloudFrontUrl",
    Value=GetAtt(cloudfront_distro, "DomainName")
))

print template.to_json()
