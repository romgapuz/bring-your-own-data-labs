var AWS = require('aws-sdk');
AWS.config.update({region: process.env['REGION']});
s3 = new AWS.S3();

exports.handler = async (event, context, callback) => {
    let source_object = process.env['SOURCE_BUCKET'] + '/' + event.source_object + '?versionId=' + event.source_version;
    let dest_object = process.env['STAGE_BUCKET'] + '/' + event.source_object;

    s3.copyObject({
      CopySource: source_object,
      Bucket: process.env['STAGE_BUCKET'],
      Key: event.source_object
    }, function(err, res) {
      if (err) {
        console.log('[ERROR]: ', err);
      } else {
        console.log('[SUCCESS]');
      }
    });
    callback(null, 'DONE');
};