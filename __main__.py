from pulumi import export, ResourceOptions, Config, Output
import pulumi_aws as aws
import json
import pulumi_random as random

config = Config()
region = config.get("aws:region")

random_string = random.RandomString("randomString",
    length=8,
    special=False)

# Create an ECS cluster to run a container-based service.
cluster = aws.ecs.Cluster('cluster')

# Read back the default VPC and public subnets, which we will use.
default_vpc = aws.ec2.get_vpc(default=True)
default_vpc_subnets = aws.ec2.get_subnet_ids(vpc_id=default_vpc.id)

# Create a SecurityGroup that permits HTTP ingress and unrestricted egress.
group = aws.ec2.SecurityGroup('web-secgrp',
	vpc_id=default_vpc.id,
	description='Enable HTTP access',
	ingress=[aws.ec2.SecurityGroupIngressArgs(
		protocol='tcp',
		from_port=80,
		to_port=80,
		cidr_blocks=['0.0.0.0/0'],
	)],
  	egress=[aws.ec2.SecurityGroupEgressArgs(
		protocol='-1',
		from_port=0,
		to_port=0,
		cidr_blocks=['0.0.0.0/0'],
	)],
)

cg = aws.ec2.SecurityGroup('container-secgrp',
	vpc_id=default_vpc.id,
	description='Enable HTTP access',
	ingress=[aws.ec2.SecurityGroupIngressArgs(
		protocol='tcp',
		from_port=8888,
		to_port=8888,
		cidr_blocks=['0.0.0.0/0'],
	)],
  	egress=[aws.ec2.SecurityGroupEgressArgs(
		protocol='-1',
		from_port=0,
		to_port=0,
		cidr_blocks=['0.0.0.0/0'],
	)],
)


# Create a load balancer to listen for HTTP traffic on port 80.
alb = aws.lb.LoadBalancer('app-lb',
	security_groups=[group.id],
	subnets=default_vpc_subnets.ids,
)

atg = aws.lb.TargetGroup('app-tg',
	port=8888,
	protocol='HTTP',
	target_type='ip',
	vpc_id=default_vpc.id,
)

wl = aws.lb.Listener('web',
	load_balancer_arn=alb.arn,
	port=80,
	default_actions=[aws.lb.ListenerDefaultActionArgs(
		type='forward',
		target_group_arn=atg.arn,
	)],
)

# Create an IAM role that can be used by our service's task.
role = aws.iam.Role('task-exec-role',
	assume_role_policy=json.dumps({
		'Version': '2008-10-17',
		'Statement': [{
			'Sid': '',
			'Effect': 'Allow',
			'Principal': {
				'Service': 'ecs-tasks.amazonaws.com'
			},
			'Action': 'sts:AssumeRole',
		}]
	}),
)

rpa = aws.iam.RolePolicyAttachment('task-exec-policy',
	role=role.name,
	policy_arn='arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy',
)

jupyter_ecs_log_group = aws.cloudwatch.LogGroup("jupyter_ecs_log_group", tags={
    "Application": "datascience-notebook",
    "Environment": "test",
})

# Spin up a load balanced service running our container image.
# task_definition = aws.ecs.TaskDefinition('app-task',
#     family='fargate-task-definition',
#     cpu='256',
#     memory='512',
#     network_mode='awsvpc',
#     requires_compatibilities=['FARGATE'],
#     execution_role_arn=role.arn,
#     container_definitions=json.dumps([{
# 		'name': 'my-app',
# 		'image': 'nginx',
# 		'portMappings': [{
# 			'containerPort': 80,
# 			'hostPort': 80,
# 			'protocol': 'tcp'
# 		}]
# 	}])
# )

jupyter_task_definition = aws.ecs.TaskDefinition("jupyterTaskDefinition",
    family=random_string.result.apply(lambda result: f"jupyter-{result}"),
    requires_compatibilities=["FARGATE"],
    network_mode="awsvpc",
    cpu=256,
    memory=512,
    execution_role_arn=role.arn,
    container_definitions=json.dumps([{
        # "entryPoint": ["start-notebook.sh","--NotebookApp.token=abcd1234efgh5678"],
        # "essential": True,
		"image": "registry.hub.docker.com/spara/nginx-test:latest",
        # "image": "public.ecr.aws/z3f3a5s9/jupyterhub/datascience-notebook:latest",
        "name": "jupyter",
        "portMappings": [
            {
                "containerPort": 8888,
                "hostPort": 8888
            }
        ],
        "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                  "awslogs-region": "us-west-2",
                  "awslogs-group": "jupyter_ecs_log_group",
                  "awslogs-stream-prefix": "54321-"
            }
        }
    }
  ]),
	opts=ResourceOptions(depends_on=[wl]),  
)

# service = aws.ecs.Service('app-svc',
# 	cluster=cluster.arn,
#     desired_count=3,
#     launch_type='FARGATE',
#     task_definition=task_definition.arn,
#     network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
# 		assign_public_ip=True,
# 		subnets=default_vpc_subnets.ids,
# 		security_groups=[group.id],
# 	),
#     load_balancers=[aws.ecs.ServiceLoadBalancerArgs(
# 		target_group_arn=atg.arn,
# 		container_name='my-app',
# 		container_port=80,
# 	)],
#     opts=ResourceOptions(depends_on=[wl]),
# )

jupyter_service = aws.ecs.Service("jupyterService",
    cluster=cluster.id,
    task_definition=jupyter_task_definition.id,
    desired_count=1,
    launch_type="FARGATE",
    network_configuration={
        "subnets": default_vpc_subnets.ids,
        "security_groups": [group.id, cg.id],
    },
    load_balancers=[{
        "target_group_arn": atg.arn,
        "container_name": "jupyter",
        "containerPort": 8888,
    }],
    opts=ResourceOptions(depends_on=[atg]))

export('url', alb.dns_name)
