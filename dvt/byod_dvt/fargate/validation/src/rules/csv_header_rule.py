import boto3
import pandas as pd
import os
import io
import re
import csv
from rules.validation_rule import ValidationRule


class CsvHeaderRule(ValidationRule):
    def validate(self, obj):
        error_messages = []

        # Read a portion of the object body
        sample_size = 1024

        df = pd.read_csv(io.BytesIO(
            obj['Body'].read(sample_size)), encoding='utf8')

        df.to_csv("test.csv", index=False)

        has_header = None

        with open('test.csv', 'r') as csvfile:
            sniffer = csv.Sniffer()
            has_header = sniffer.has_header(csvfile.read())

        if not has_header:
            error_messages.append(['error', 'File has no headers'])

        # Validate column names
        pattern = re.compile('^[0-9]|[@_!#$%^&*()<>?/|}{~: ]')
        col_status = []
        col_name = []

        for col in df.columns:
            col_name.append(col)
            if(pattern.search(col) == None):
                col_status.append(True)
            else:
                col_status.append(False)

        has_valid_col_name = True if sum(
            bool(stat) for stat in col_status) == len(df.columns) else False

        for name, status in zip(col_name, col_status):
            error_messages.append(["error",
                                   "Column name <{}>".format(name) + (
                                       " is valid" if status == True else " is not valid")])

        return (not has_valid_col_name or not has_header), error_messages
