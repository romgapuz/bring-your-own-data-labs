import os
import boto3
import uuid
import datetime

dynamodb = boto3.resource('dynamodb')
sqs = boto3.client('sqs')

TABLE_NAME = os.environ['TABLE_NAME']
QUEUE_URL = os.environ['QUEUE_URL']


def lambda_handler(event, context):
    print('Received event: \n' + str(event))

    table = dynamodb.Table(TABLE_NAME)

    for record in event['Records']:
        job_id = str(uuid.uuid4())
        d = datetime.datetime.utcnow()

        response = table.put_item(
            Item={
                'id': job_id,
                'start_ts': datetime.datetime.utcnow().isoformat(),
                'createdAt': d.isoformat() + 'Z',
                'updatedAt': d.isoformat() + 'Z',
                'filename': record['s3']['object']['key'],
                'filename_version': record['s3']['object']['versionId'],
                'status': 'pending',
                'warnings': 0,
                'errors': 0,
                'staged': 'no'
            }
        )
        print('DynamoDB response: %s' % (response))

        response = sqs.send_message(
            QueueUrl=QUEUE_URL,
            DelaySeconds=10,
            MessageAttributes={},
            MessageBody=(job_id)
        )
        print('SQS response: %s' % (response))
