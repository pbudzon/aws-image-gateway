import boto3
from PIL import Image
from io import BytesIO


def lambda_handler(event, context):
    if 'image' not in event:
        raise Exception("No image specified")

    if 'bucket' not in event:
        raise Exception("No storage bucket configured")

    client = boto3.client('s3')

    requested_file = str(event['image'])

    width = 5
    if 'width' in event and event['width']:
        width = int(event['width'])

    height = 5
    if 'height' in event and event['height']:
        height = int(event['height'])

    try:
        response = client.get_object(
            Bucket=event['bucket'],
            Key=requested_file
        )
    except Exception:
        print("Error when fetching image: " + requested_file)
        raise Exception("Not found")

    if response['ResponseMetadata']['HTTPStatusCode'] != 200:
        raise Exception("Error: Could not fetch the image")

    image = Image.open(response['Body'])
    size = width, height

    image.thumbnail(size)
    output = BytesIO()
    image.save(output, format=image.format)
    output.seek(0)
    output_name = requested_file + '-' + str(width) + 'x' + str(height) + '.' + image.format.lower()

    response = client.put_object(
        ACL='public-read',
        Bucket=event['bucket'],
        Body=output,
        ContentType='image/' + image.format.lower(),
        Key='images/' + output_name
    )

    if response['ResponseMetadata']['HTTPStatusCode'] != 200:
        raise Exception("Error: Could not write the image")

    return {"location": "/images/" + output_name}


if __name__ == '__main__':
    print lambda_handler({'width': 100, 'height': 100, 'image': 'download.jpeg', 'bucket': 'test-image-gateway'}, None)
