from clevercsv import read_dataframe
from rules import CsvHeaderRule
from rules import FileSizeEncodingRule
import boto3
import s3fs
import csv
import os
import time
import datetime

TABLE_NAME = os.environ['TABLE_NAME']
QUEUE_URL = os.environ['QUEUE_URL']
SOURCE_BUCKET_NAME = os.environ['SOURCE_BUCKET_NAME']
TARGET_BUCKET_NAME = os.environ['TARGET_BUCKET_NAME']
REGION = os.environ['REGION']

sqs = boto3.client('sqs', region_name=REGION)
s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb', region_name=REGION)

if __name__ == "__main__":
    # collecting queue message one by one until queue is empty
    while True:
        response = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            AttributeNames=[
                'SentTimestamp'
            ],
            MaxNumberOfMessages=1,
            MessageAttributeNames=[
                'All'
            ],
            VisibilityTimeout=0,
            WaitTimeSeconds=0
        )

        try:
            # read SQS message
            receipt_handle = response['Messages'][0]['ReceiptHandle']
            job_id = response['Messages'][0]['Body']

            # get job from DDB
            print('Retrieving job %s from DynamoDB...' % (job_id))
            table = dynamodb.Table(TABLE_NAME)
            response = table.get_item(Key={'id': job_id})

            print('Retrieving csv file from S3...')
            filename = '%s.csv' % (job_id)
            obj = s3.get_object(
                Bucket=SOURCE_BUCKET_NAME,
                Key=response['Item']['filename'],
                VersionId=response['Item']['filename_version']
            )

            # run validation rules
            rule1 = CsvHeaderRule()
            print('Validating if header exist and header names...')
            r1_err, r1_messages = rule1.validate(obj)
            rule2 = FileSizeEncodingRule()
            print('Validating file size and encoding...')
            r2_err, r2_messages = rule2.validate(obj)
            print('Validation done')

            # if there are errors...
            if (r1_err or r2_err):
                print('Error found')

                # generate csv
                print('Generating error messages csv file...')
                error_messages = r1_messages + r2_messages
                with open(filename, mode='w') as result_csv:
                    writer = csv.writer(
                        result_csv, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                    writer.writerow(['type', 'message'])
                    for err in error_messages:
                        writer.writerow(err)

                # upload csv to S3
                print('Uploading to S3...')
                response = s3.upload_file(
                    filename, TARGET_BUCKET_NAME, 'validation/%s' % (filename))
                print('S3 response: %s' % (response))

                # count errors and warnings
                errors = 0
                warnings = 0
                for err in error_messages:
                    if err[0] == 'error':
                        errors = errors + 1
                    else:
                        warnings = warnings + 1
                print('Found %d warnings and %d errors' % (warnings, errors))

                # update DDB table
                print('Updating job in DynamoDB...')
                response = table.update_item(
                    Key={
                        'id': job_id
                    },
                    UpdateExpression="set result_uri = :r, warnings = :w, errors = :e, #status = :s, end_ts = :d",
                    ExpressionAttributeValues={
                        ':r': 'https://%s.s3-%s.amazonaws.com/validation/%s' % (TARGET_BUCKET_NAME, REGION, filename),
                        ':w': warnings,
                        ':e': errors,
                        ':s': 'failed' if errors > 0 else 'success',
                        ':d': datetime.datetime.utcnow().isoformat()
                    },
                    ExpressionAttributeNames={
                        '#status': 'status'
                    },
                    ReturnValues="UPDATED_NEW"
                )
                print('DynamoDB response: %s' % (response))
            else:
                print('No error found')
                print('Updating job in DynamoDB...')
                response = table.update_item(
                    Key={
                        'id': job_id
                    },
                    UpdateExpression="set #status = :s, end_ts = :d",
                    ExpressionAttributeValues={
                        ':s': 'success',
                        ':d': datetime.datetime.utcnow().isoformat()
                    },
                    ExpressionAttributeNames={
                        '#status': 'status'
                    },
                    ReturnValues="UPDATED_NEW"
                )
                print('DynamoDB response: %s' % (response))

            # Delete received message from queue
            print('Deleting SQS message from queue...')
            sqs.delete_message(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=receipt_handle
            )

            print('Validation job done')

        # Manage case queue is empty
        except KeyError:
            print('No messages anymore')

        except Exception as error:
            print('Uncaught exception: %s' % (error))

        time.sleep(1)
