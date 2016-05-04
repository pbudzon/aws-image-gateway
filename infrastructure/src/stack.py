from troposphere import GetAtt, Ref, Template, Output, Parameter, Join
from troposphere.s3 import Bucket, LifecycleConfiguration, LifecycleRule, WebsiteConfiguration
from troposphere.iam import Role, Policy as IAMPolicy
from troposphere.awslambda import Function, Code, Permission
from troposphere.cloudfront import Distribution, DistributionConfig, CustomOrigin, DefaultCacheBehavior, \
    ForwardedValues, CacheBehavior, CustomErrorResponse
from troposphere.apigateway import RestApi, Resource, Method, Integration, IntegrationResponse, MethodResponse, \
    Deployment, StageDescription
from awacs.aws import Statement, Allow, Principal, Action, Policy
from awacs.sts import AssumeRole

t = Template()

t.add_description("Image gateway")

t.add_metadata({
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

param_bucket_name = t.add_parameter(Parameter(
    "BucketName",
    Type="String",
    Description='Name of the STORAGE bucket to create where the images will be uploaded and renditions cached'
))

param_lambda_source_bucket = t.add_parameter(Parameter(
    "LambdaSourceBucket",
    Type="String",
    Description="Name of the bucket where lambda function sources is stored"
))

param_lambda_file_name = t.add_parameter(Parameter(
    "LambdaFileName",
    Type="String",
    Description="Name of the ZIP file with lambda function sources inside LambdaSourceBucket"
))

bucket = t.add_resource(Bucket(
    "StorageBucket",
    AccessControl='Private',
    BucketName=Ref(param_bucket_name),
    LifecycleConfiguration=LifecycleConfiguration(
        Rules=[
            LifecycleRule(
                Prefix="images/",
                Status="Enabled",
                ExpirationInDays=14
            )
        ]
    ),
    WebsiteConfiguration=WebsiteConfiguration(
        IndexDocument="index.html"
    )
))

lambda_role = t.add_resource(Role(
    "LambaRole",
    AssumeRolePolicyDocument=Policy(
        Statement=[
            Statement(
                Effect=Allow, Action=[AssumeRole],
                Principal=Principal(
                    "Service", ["lambda.amazonaws.com"]
                )
            )
        ]
    ),
    Policies=[
        IAMPolicy(
            PolicyName="ImgGatewayLambaPolicy",
            PolicyDocument=Policy(
                Statement=[
                    Statement(
                        Effect=Allow,
                        Action=[
                            Action("logs", "CreateLogGroup"),
                            Action("logs", "CreateLogStream"),
                            Action("logs", "PutLogEvents"),
                        ],
                        Resource=["arn:aws:logs:*:*:*"]
                    ),
                    Statement(
                        Effect=Allow,
                        Action=[
                            Action("s3", "GetObject")
                        ],
                        Resource=[
                            Join("", ["arn:aws:s3:::", Ref(bucket), "/*"])
                        ]
                    ),
                    Statement(
                        Effect=Allow,
                        Action=[
                            Action("s3", "PutObject*")
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

lambda_function = t.add_resource(Function(
    "Lambda",
    Code=Code(
        S3Bucket=Ref(param_lambda_source_bucket),
        S3Key=Ref(param_lambda_file_name)
    ),
    Handler="lambda.lambda_handler",
    MemorySize=128,
    Role=GetAtt(lambda_role, "Arn"),
    Runtime="python2.7",
    Timeout=30
))

api = t.add_resource(RestApi(
    "API",
    Description="Image Gateway API",
    Name="ImageGateway"
))

cloudfront = t.add_resource(Distribution(
    "CloudFrontDistribution",
    DistributionConfig=DistributionConfig(
        Comment="Image Gateway",
        Enabled=True,
        DefaultCacheBehavior=DefaultCacheBehavior(
            ForwardedValues=ForwardedValues(
                QueryString=True,
                Headers=["Location"]
            ),
            TargetOriginId="lambda",
            ViewerProtocolPolicy="allow-all"
        ),
        CacheBehaviors=[
            CacheBehavior(
                TargetOriginId="bucket",
                DefaultTTL=86400,
                PathPattern="images/*",
                ForwardedValues=ForwardedValues(
                    QueryString=False,
                ),
                ViewerProtocolPolicy="allow-all"
            )
        ],
        Origins=[
            {
                "CustomOriginConfig": CustomOrigin(
                    OriginProtocolPolicy="https-only"
                ),
                "DomainName": Join("", [Ref(api), ".execute-api.", Ref("AWS::Region"), ".amazonaws.com"]),
                "OriginPath": "/live",
                "Id": "lambda"
            },
            {
                "CustomOriginConfig": CustomOrigin(
                    OriginProtocolPolicy="http-only"
                ),
                "DomainName": Join("", [Ref(bucket), ".s3-website-", Ref("AWS::Region"), ".amazonaws.com"]),
                "Id": "bucket"
            }

        ],
        PriceClass='PriceClass_100',
        CustomErrorResponses=[
            CustomErrorResponse(
                ErrorCode=403,
                ErrorCachingMinTTL=0
            ),
            CustomErrorResponse(
                ErrorCode=404,
                ErrorCachingMinTTL=0
            )
        ]
    )
))

api_image_resource = t.add_resource(Resource(
    "APIImageResource",
    ParentId=GetAtt(api, "RootResourceId"),
    PathPart="{image}",
    RestApiId=Ref(api)
))

api_image_method = t.add_resource(Method(
    "APIImageMethodGET",
    ApiKeyRequired=False,
    AuthorizationType="NONE",
    HttpMethod="GET",
    ResourceId=Ref(api_image_resource),
    RestApiId=Ref(api),
    Integration=Integration(
        Type="AWS",
        IntegrationHttpMethod="POST",
        Uri=Join("", [
            "arn:aws:apigateway:", Ref("AWS::Region"), ":lambda:path/2015-03-31/functions/",
            GetAtt(lambda_function, "Arn"),
            "/invocations"
        ]),
        RequestTemplates={
            "application/json": Join("", [
                "{\"width\": \"$input.params('width')\", \"image\": \"$input.params('image')\", \"height\": \"$input.params('height')\", \"bucket\":\"",
                Ref(param_bucket_name),
                "\", \"cloudfront\":\"", GetAtt(cloudfront, "DomainName"), "\"}"
            ])
        },
        IntegrationResponses=[
            IntegrationResponse(
                "IntegrationResponse",
                StatusCode="302",
                ResponseParameters={
                    "method.response.header.Location": "integration.response.body.location"
                },
                ResponseTemplates={
                    "application/json": "$input.params('whatever')"
                }
            ),
            IntegrationResponse(
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
        MethodResponse(
            "APIResponse",
            StatusCode="302",
            ResponseParameters={
                "method.response.header.Location": True
            }
        ),
        MethodResponse(
            "APIResponse",
            StatusCode="404"
        )
    ]
))

api_lambda_permission = t.add_resource(Permission(
    "APILambdaPermission",
    Action="lambda:InvokeFunction",
    FunctionName=Ref(lambda_function),
    Principal="apigateway.amazonaws.com",
    SourceArn=Join("", [
        "arn:aws:execute-api:", Ref("AWS::Region"), ":", Ref("AWS::AccountId"), ":", Ref(api), "/*/GET/*"
    ])
))

api_deployment = t.add_resource(Deployment(
    "APIDeployment",
    RestApiId=Ref(api),
    StageName="live",
    StageDescription=StageDescription(
        CacheClusterEnabled=False,
    )
))

t.add_output(Output(
    "CloudfrontUrl",
    Value=GetAtt(cloudfront, "DomainName")
))

print t.to_json()
