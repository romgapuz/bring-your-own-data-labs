from aws_cdk import (
    core,
    aws_lambda as _lambda,
    aws_s3 as _s3,
    aws_cognito as _cognito,
    aws_dynamodb as _dynamodb,
    aws_appsync as _appsync,
    aws_ec2 as _ec2,
    aws_sqs as _sqs,
    aws_iam as _iam,
    aws_ecs as _ecs,
    aws_ecs_patterns as _ecs_patterns,
    aws_ecr_assets as _ecr_assets
)
from aws_cdk.aws_lambda_event_sources import S3EventSource as _S3EventSource
from aws_cdk.aws_appsync import AuthorizationConfig, AuthorizationMode, AuthorizationType, UserPoolConfig, LogConfig, FieldLogLevel
from aws_cdk.aws_iam import FederatedPrincipal, PolicyStatement, Effect
import os

dirname = os.path.dirname(__file__)


class ByodDvtStack(core.Stack):

    def __init__(self, scope: core.Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        ### S3 ###

        source_csv_bucket = _s3.Bucket(
            self,
            "BYODValidationSourceBucket",
            versioned=True
        )

        target_csv_bucket = _s3.Bucket(
            self,
            "BYODValidationTargetBucket",
            removal_policy=core.RemovalPolicy.RETAIN
        )

        ### Cognito ###

        userpool = _cognito.UserPool(
            self,
            "WebToolUserPool",
            user_pool_name="byod-webtool-userpool",
            self_sign_up_enabled=True,
            auto_verify={
                "email": True,
                "phone": False
            },
            user_verification={
                "email_subject": "Your verification code",
                "email_body": "Your verification code is {####}",
                "email_style": _cognito.VerificationEmailStyle.CODE
            },
            standard_attributes={
                "email": {
                    "required": True,
                    "mutable": False
                }
            },
            password_policy={}
        )
        client = userpool.add_client(
            "webtool-app-client",
            auth_flows={
                "custom": True,
                "user_password": True,
                "user_srp": True,
                "refresh_token": True
            }
        )
        identity_pool = _cognito.CfnIdentityPool(
            self,
            "WebToolCognitoIdentityPool",
            allow_unauthenticated_identities=True
        )
        identity_pool.add_property_override("CognitoIdentityProviders", [{
            "ClientId": client.user_pool_client_id,
            "ProviderName": userpool.user_pool_provider_name
        }])
        auth_role = _iam.Role(
            self,
            "CognitoAuthRole",
            assumed_by=FederatedPrincipal(
                "cognito-identity.amazonaws.com",
                {
                    "StringEquals": {
                        "cognito-identity.amazonaws.com:aud": identity_pool.ref
                    },
                    "ForAnyValue:StringLike": {
                        "cognito-identity.amazonaws.com:amr": "authenticated"
                    }
                }
            )
        )
        auth_role.add_to_policy(PolicyStatement(
            effect=Effect.ALLOW,
            actions=[
                "s3:GetObject"
            ],
            resources=[
                "%s/*" % target_csv_bucket.bucket_arn
            ]
        ))
        unauth_role = _iam.Role(
            self,
            "CognitoUnauthRole",
            assumed_by=_iam.FederatedPrincipal(
                "cognito-identity.amazonaws.com",
                conditions={
                    "StringEquals": {
                        "cognito-identity.amazonaws.com:aud": identity_pool.ref
                    },
                    "ForAnyValue:StringLike": {
                        "cognito-identity.amazonaws.com:amr": "unauthenticated"
                    }
                }
            )
        )
        identity_pool_policy = _cognito.CfnIdentityPoolRoleAttachment(
            self,
            "WebToolCognitoIdentityPoolPolicy",
            identity_pool_id=identity_pool.ref,
            roles={
                'unauthenticated': unauth_role.role_arn,
                'authenticated': auth_role.role_arn
            }
        )
        core.CfnOutput(self, "UserPoolId", value=userpool.user_pool_id)
        core.CfnOutput(self, "ClientId", value=client.user_pool_client_id)
        core.CfnOutput(self, "ProviderName",
                       value=userpool.user_pool_provider_name)

        ### DynamoDB ###

        validation_job_table = _dynamodb.Table(
            self,
            "ValidationJobTable",
            partition_key=_dynamodb.Attribute(
                name="id",
                type=_dynamodb.AttributeType.STRING
            )
        )

        ## AppSync ###

        api = _appsync.GraphqlApi(
            self,
            "Api",
            name="validation-job-api",
            schema=_appsync.Schema.from_asset(
                os.path.join(dirname, "api", "schema.graphql")),
            authorization_config=AuthorizationConfig(
                default_authorization=AuthorizationMode(
                    authorization_type=AuthorizationType.USER_POOL,
                    user_pool_config=UserPoolConfig(user_pool=userpool)
                )
            ),
            log_config=LogConfig(
                exclude_verbose_content=False,
                field_log_level=FieldLogLevel.ALL
            )
        )
        api_ds = api.add_dynamo_db_data_source(
            "ValidationJobDataSource", validation_job_table)
        core.CfnOutput(self, "GraphQLEndpoint", value=api.graphql_url)

        ### SQS ###

        validation_job_queue = _sqs.Queue(
            self,
            "ValidationJobQueue"
        )

        profiling_job_queue = _sqs.Queue(
            self,
            "ProfilingJobQueue"
        )

        ### Lambda ###

        validation_trigger_function = _lambda.Function(
            self,
            "ValidationTriggerFunction",
            runtime=_lambda.Runtime.PYTHON_3_8,
            code=_lambda.Code.from_asset(os.path.join(
                dirname, "lambda", "validation_trigger")),
            handler='lambda_function.lambda_handler'
        )

        validation_trigger_function.add_environment(
            "TABLE_NAME", validation_job_table.table_name)
        validation_trigger_function.add_environment(
            "QUEUE_URL", validation_job_queue.queue_url)

        validation_trigger_function.add_event_source(
            _S3EventSource(
                source_csv_bucket,
                events=[_s3.EventType.OBJECT_CREATED]
            )
        )

        source_csv_bucket.grant_read(validation_trigger_function)
        validation_job_table.grant_read_write_data(validation_trigger_function)
        validation_job_queue.grant_send_messages(validation_trigger_function)

        stager_function = _lambda.Function(
            self,
            "StagerFunction",
            runtime=_lambda.Runtime.NODEJS_12_X,
            code=_lambda.Code.from_asset(
                os.path.join(dirname, "lambda", "stager")),
            handler='index.handler'
        )

        stager_function.add_environment("REGION", self.region)
        stager_function.add_environment(
            "SOURCE_BUCKET", source_csv_bucket.bucket_name)
        stager_function.add_environment(
            "STAGE_BUCKET", target_csv_bucket.bucket_name)
        source_csv_bucket.grant_read(stager_function)
        target_csv_bucket.grant_put(stager_function)

        ### ECS Fargate ###

        validation_fargate_asset = _ecr_assets.DockerImageAsset(
            self,
            "ValidationBuildImage",
            directory=os.path.join(dirname, "fargate", "validation")
        )
        profiling_fargate_asset = _ecr_assets.DockerImageAsset(
            self,
            "ProfilingBuildImage",
            directory=os.path.join(dirname, "fargate", "profiling")
        )

        vpc = _ec2.Vpc(self, "VPC", max_azs=3)
        cluster = _ecs.Cluster(
            self,
            "ECSCluster",
            vpc=vpc
        )

        validation_fargate_service = _ecs_patterns.QueueProcessingFargateService(
            self,
            "ValidationFargateService",
            cluster=cluster,
            cpu=4096,
            memory_limit_mib=30720,
            enable_logging=True,
            image=_ecs.ContainerImage.from_docker_image_asset(
                validation_fargate_asset),
            environment={
                "TABLE_NAME": validation_job_table.table_name,
                "QUEUE_URL": validation_job_queue.queue_url,
                "SOURCE_BUCKET_NAME": source_csv_bucket.bucket_name,
                "TARGET_BUCKET_NAME": target_csv_bucket.bucket_name,
                "REGION": self.region
            },
            queue=validation_job_queue,
            max_scaling_capacity=2,
            max_healthy_percent=200,
            min_healthy_percent=66
        )
        validation_fargate_service.task_definition.task_role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name("AmazonDynamoDBFullAccess"))
        validation_fargate_service.task_definition.task_role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3FullAccess"))

        profiling_fargate_service = _ecs_patterns.QueueProcessingFargateService(
            self,
            "ProfilingFargateService",
            cluster=cluster,
            cpu=4096,
            memory_limit_mib=30720,
            enable_logging=True,
            image=_ecs.ContainerImage.from_docker_image_asset(
                profiling_fargate_asset),
            environment={
                "TABLE_NAME": validation_job_table.table_name,
                "QUEUE_URL": profiling_job_queue.queue_url,
                "SOURCE_BUCKET_NAME": source_csv_bucket.bucket_name,
                "TARGET_BUCKET_NAME": target_csv_bucket.bucket_name,
                "REGION": self.region
            },
            queue=profiling_job_queue,
            max_scaling_capacity=2,
            max_healthy_percent=200,
            min_healthy_percent=66
        )
        profiling_fargate_service.task_definition.task_role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name("AmazonDynamoDBFullAccess"))
        profiling_fargate_service.task_definition.task_role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3FullAccess"))
