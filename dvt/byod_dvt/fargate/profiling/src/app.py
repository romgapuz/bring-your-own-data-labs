import pandas as pd
import boto3
from botocore.config import Config
from pandas_profiling import ProfileReport
from io import StringIO
import io
import time
import os
import datetime
import http.client
import json
import pytz

TABLE_NAME = os.environ['TABLE_NAME']
QUEUE_URL = os.environ['QUEUE_URL']
SOURCE_BUCKET_NAME = os.environ['SOURCE_BUCKET_NAME']
TARGET_BUCKET_NAME = os.environ['TARGET_BUCKET_NAME']
REGION = os.environ['REGION']

sqs = boto3.client('sqs', region_name=REGION)
s3c = boto3.client('s3')
dynamodb = boto3.resource('dynamodb', region_name=REGION)


def updateS3link(jobID, s3link, start_time_ts, end_time_ts):
    table = dynamodb.Table(TABLE_NAME)
    response = table.get_item(Key={'id': jobID})
    response = table.update_item(
        Key={
            'id': jobID
        },
        UpdateExpression="set profile_uri = :u, profile_start_ts = :st, profile_end_ts = :et",
        ExpressionAttributeValues={
            ':u': s3link,
            ':st': start_time_ts,
            ':et': end_time_ts
        },
        ReturnValues="UPDATED_NEW"
    )
    print('DynamoDB response: %s' % (response))


if __name__ == "__main__":

    # Infinite Loop to poll queue
    while True:

        # visibility timeout of 12 Hours to prevent other consumers from processing same file
        response = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            AttributeNames=[
                'SentTimestamp'
            ],
            MaxNumberOfMessages=1,
            MessageAttributeNames=[
                'All'
            ],
            VisibilityTimeout=43200,
            WaitTimeSeconds=1
        )

        # check if there's a message in the queue
        try:
            # read SQS message
            receipt_handle = response['Messages'][0]['ReceiptHandle']
            jobID = response['Messages'][0]['MessageAttributes']['jobid']['StringValue']

            # get job from DDB
            print('Retrieving job %s from DynamoDB...' % (jobID))
            table = dynamodb.Table(TABLE_NAME)
            response = table.get_item(Key={'id': jobID})

            print('Retrieving csv file from S3...')
            filename = '%s.csv' % (jobID)
            obj = s3c.get_object(
                Bucket=SOURCE_BUCKET_NAME,
                Key=response['Item']['filename'],
                VersionId=response['Item']['filename_version']
            )

            df = pd.read_csv(io.BytesIO(
                obj['Body'].read()), encoding='utf8', header=0, sep=",")
            start_time_ts = datetime.datetime.utcnow().isoformat()

            #--------------------PROFILING CODE --------------------------#
            # generate html report
            profile = ProfileReport(df, title="Pandas Profiling Report")
            profile.to_file(jobID+"_profiling_report.html")

            # upload to s3
            filename = jobID+'_profiling_report.html'

            # upload csv to S3
            print('Uploading to S3...')
            response = s3c.upload_file(
                filename, TARGET_BUCKET_NAME, 'profiling/%s' % (filename))
            print('S3 response: %s' % (response))
            #--------------------/PROFILING CODE -------------------------#

            # delete file from local directory
            os.remove(filename)

            path = 'https://%s.s3-%s.amazonaws.com/validation/%s' % (
                TARGET_BUCKET_NAME, REGION, filename)

            # updateDynamoDB with location of s3 profiling report
            end_time_ts = datetime.datetime.utcnow().isoformat()
            updateS3link(jobID, path, start_time_ts, end_time_ts)

            # Delete message from queue after processing
            print('Deleting SQS message from queue...')
            sqs.delete_message(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=receipt_handle
            )

            print('Profling job done')

        #queue is empty

        except KeyError:
            print('no messages')

        except Exception as error:
            print('Uncaught exception: %s' % (error))

        time.sleep(1)
