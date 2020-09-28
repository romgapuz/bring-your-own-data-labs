import boto3
import pandas as pd
import os
import io
import re
from rules.validation_rule import ValidationRule


class FileSizeEncodingRule(ValidationRule):
    def validate(self, obj):
        error_messages = []

        '''Validate File Size'''
        file_size_unit = 1024 * 1024 * 1024
        file_size_limit = 3 * file_size_unit  # 3 GiB file size limit
        file_size = obj['ContentLength']

        is_within_filesize = (file_size <= file_size_limit)
        if not is_within_filesize:
            error_messages.append(["error", "Exceeds maximum file size of " +
                                   "{:.2f}".format(file_size_limit/1024/1024) + " Megabytes, your file size is " +
                                   "{:.2f}".format(file_size/1024/1024) + " Megabytes"])

        '''Validate utf-8 encoding'''
        pattern = re.compile('utf-8')
        try:
            df = pd.read_csv(io.BytesIO(obj['Body'].read()), encoding='utf8')
            is_UTF8 = True
        except ValueError as e:
            error_message = str(e)
            if (pattern.search(error_message) == None):
                is_UTF8 = False
                error_messages.append(['error', error_message])
            else:
                is_UTF8 = False
                error_messages.append(['error', "UTF-8 encoding error"])

        return (not is_within_filesize or not is_UTF8), error_messages
