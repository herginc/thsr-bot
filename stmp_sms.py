import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# from twilio.rest import Client
from config import *

pnr_code = '05428405'
train_code = 652
departure_date = '03/21'
departure_time = '15:57'
arrival_time = '16:33'
departure_stn = '新竹'
arrival_stn = '台北'
seat_lable = '1車4A'
passenger_id = 'G12*****23'
passenger_email = 'HE*****@GMAIL.COM'
TotalPrice = 'TWD 290'
status_unpaid = '未付款（付款期限：發車前30分）'
payment_deadline = '發車前30分'
# payment_deadline = '2025/04/17'
# payment_deadline = '04/17'

really_send_message = True

def send_email(email_ctx):

    if (really_send_message == True):
        # Set up the MIME
        message = MIMEMultipart()
        message['From'] = email_ctx['sender_email']
        message['To'] = email_ctx['recipient_email']
        message['Subject'] = email_ctx['email_subject']

        # Attach the body to the email
        message.attach(MIMEText(email_ctx['email_body'], 'plain'))
        
        try:
            # Create SMTP session for sending the mail
            # For Gmail, use port 587 and smtp.gmail.com
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()  # Enable security
                server.login(email_ctx['sender_email'], email_ctx['sender_password'])  # Login
                text = message.as_string()
                server.sendmail(email_ctx['sender_email'], email_ctx['recipient_email'], text)
                # print(f"email message sent successfully")
        except Exception as e:
            print(f"[send_email] Failed to send email. Error: {e}")
            return False

    # print sending status
    # print(f"\n--------------------------------------------")
    # print(f"email message sent successfully")
    # print(email_ctx['email_body'])

    print(f"\n----------- << send_email >> -----------")
    print(f"sender_email    = {email_ctx['sender_email']}")
    print(f"sender_password = {email_ctx['sender_password']}")
    print(f"recipient_email = {email_ctx['recipient_email']}")
    print(f"email_subject   = {email_ctx['email_subject']}")
    print(f"email_body = \n{email_ctx['email_body']}")


# end of send_email


def send_email_locally(sender_email, recipient_email, subject, body):
    # Set up the MIME
    message = MIMEMultipart()
    message['From'] = sender_email
    message['To'] = recipient_email
    message['Subject'] = subject
    
    # Attach the body
    message.attach(MIMEText(body, 'plain'))
    
    try:
        # Connect to local SMTP server
        with smtplib.SMTP('localhost', 1025) as server:
            # No authentication needed for local server
            server.sendmail(sender_email, recipient_email, message.as_string())
            print("[send_email_locally] Email sent to local SMTP server successfully!")
    except Exception as e:
        print(f"[send_email_locally] Failed to send email. Error: {e}")

# Example usage
def example_send_email():
    # Replace these with your actual email credentials
    sender_email = "herginc@gmail.com"
    sender_password = "wshx jnzx wubb gavn"  # For Gmail, use an App Password
    recipient_email = "herginc@yahoo.com"
    subject = "高鐵訂票成功"

    body = \
        f'訂位代號: {pnr_code}\n' \
        f'高鐵車次: {train_code}\n' \
        f'乘車日期: {departure_date}\n' \
        f'出發時間: {departure_stn} {departure_time}\n' \
        f'到達時間: {arrival_stn} {arrival_time}\n' \
        f'高鐵座位: {seat_lable}\n' \
        f'身份字號: {passenger_id}\n' \
        f'電子郵件: {passenger_email}\n' \
        f'付款資訊: {TotalPrice} {status_unpaid}'

    print(f'============== << email_message >> ==============\n{body}\n')

    # send_email(sender_email, sender_password, recipient_email, subject, body)

# Example usage
def example_send_email_locally():
    sender_email = "superman@supercom"  # Can be any address for local testing
    recipient_email = "herginc@gmail.com"
    subject = "Test Email via Local Python SMTP"
    body = """Hello,
    
This is a test email sent using Python's local SMTP server.
    
You can see this in the terminal where you started the server."""
    
    send_email_locally(sender_email, recipient_email, subject, body)



import http.client

def send_sms_d7():
    conn = http.client.HTTPSConnection("d7sms.p.rapidapi.com")

    payload = "{\"messages\":[{\"channel\":\"sms\",\"originator\":\"D7-RapidAPI\",\"recipients\":[\"+886939655161\",\"+886952655161\"],\"content\":\"This is test message from Scott \",\"data_coding\":\"text\"}]}"

    headers = {
        'x-rapidapi-host': "d7sms.p.rapidapi.com",
        'Content-Type': "application/json"
    }

    conn.request("POST", "/messages/v1/send", payload, headers)

    res = conn.getresponse()
    data = res.read()

    print(data.decode("utf-8"))


def send_sms_twilio(sms_ctx):

    # Test credentials (The SMS will not be sent to the target mobile number)
    # https://www.twilio.com/docs/iam/test-credentials
    # account_sid = 'XXXXXXXX'
    # auth_token = 'XXXXXXXX'
    # twilio_test_number = '+15005550006'
    # twilio_phone_number = twilio_test_number

    # From (Phone Num)  Description                                                             Error Code
    # +15005550001      This phone number is invalid.                                           21212
    # +15005550007      This phone number is not owned by your account or is not SMS-capable.   21606
    # +15005550008      This number has an SMS message queue that is full.                      21611
    # +15005550006      This number passes all validation.                                      No error
    # All Others        This phone number is not owned by your account or is not SMS-capable.   21606

    # To (Phone Num)    Description                                                             Error Code
    # +15005550001      This phone number is invalid.                                           21211
    # +15005550002      Twilio cannot route to this number.                                     21612
    # +15005550003      No international permissions necessary to SMS this number.              21408
    # +15005550004      This number is blocked for your account.                                21610
    # +15005550009      This number is incapable of receiving SMS messages.                     21614
    # All Others        Any other phone number is validated normally.                           Input-dependent


    account_sid = TWILIO_ACCOUNT_SID
    auth_token  = TWILIO_AUTH_TOKEN
    my_twilio_phone_number = '+19152942257'
    twilio_phone_number = my_twilio_phone_number

    client = Client(account_sid, auth_token)

    message = client.messages.create(
    from_=twilio_phone_number,
    body=sms_ctx['sms_body'],
    to=sms_ctx['phone_num']
    )

    # print sending status
    print(f"\n--------------------------------------------")
    print(f"SMS message sent successfully")
    print(f"SID: {message.sid}")
    print(f"Status: {message.status}")
    print(f"Datetime: {message.date_created}")
    print(f"Num_Segments: {message.num_segments}")
    print(f"Price: {message.price} ({message.price_unit})\n")

    # print(message.sid)

def send_sms(sms_ctx):

    if (really_send_message == True):
        try:
            send_sms_twilio(sms_ctx)
        except Exception as e:
            print(f"Send failed: {str(e)}")
            # print(e)
            return False

    print(f"\n----------- << send_sms >> -----------")
    print(f"phone_num    = {sms_ctx['phone_num']}")
    print(f"sms_body = \n{sms_ctx['sms_body']}")


def example_send_sms():
    phone_num = '+886939655161'    # Scott
    # phone_num = '+886906356120'    # Dana

    # SMS message length calculator:
    # https://messente.com/sms-length-calculator
    # https://freetools.textmagic.com/sms-length-calculator

    # Sent from your Twilio trial account - 
    # Reservation: 05428405
    # Date: 03/21, HSU 15:57 - TPE 16:33
    # Seat: 1-4A
    # ID No: G12*****23
    # Price: TWD 290 (Due: 03/21)

    if (payment_deadline == '發車前30分'):
        payment_deadline_e = departure_date
    else:
        payment_deadline_e = payment_deadline[-5:]
        try:
            datetime.strptime(payment_deadline_e, '%m/%d')
        except:
            print(f'Invalid Date: {payment_deadline}')
            payment_deadline_e = 'TBD'
            pass

    seat_lable_e = seat_lable.replace("車", "-")
    departure_stn_e = chinese_station_to_english_station(departure_stn)
    arrival_stn_e = chinese_station_to_english_station(arrival_stn)

    body = \
        f'\nReservation: {pnr_code}\n' + \
        f'Date: {departure_date}, {departure_stn_e} {departure_time} - {arrival_stn_e} {arrival_time}\n' + \
        f'Seat: {seat_lable_e}\n' + \
        f'ID No: {passenger_id}\n' + \
        f'Price: {TotalPrice} (Due: {payment_deadline_e})'

    print(f'============== << SMS_message >> ==============\n{body}\n')
    # send_sms(phone_num, body)

def chinese_station_to_english_station(stn):
    if (stn == "新竹"):
        return "HSU"
    elif (stn == "台北"):
        return "TPE"
    else:
        return "XXX"


import requests
import json

def example_send_LINE_message():
    # Replace with your actual Channel Access Token
    CHANNEL_ACCESS_TOKEN = "YOUR_CHANNEL_ACCESS_TOKEN"

    # Replace with the recipient's User ID
    USER_ID = "RECIPIENT_USER_ID"

    # The message you want to send
    message = {
        "type": "text",
        "text": "Hello! This is a test message sent via the LINE Messaging API."
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"
    }

    data = {
        "to": USER_ID,
        "messages": [message]
    }

    try:
        response = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers=headers,
            data=json.dumps(data)
        )
        response.raise_for_status()  # Raise an exception for bad status codes
        print("Message sent successfully!")
    except requests.exceptions.RequestException as e:
        print(f"Error sending message: {e}")
        if response is not None:
            print(f"Response content: {response.text}")


from linebot import LineBotApi
from linebot.models import TextSendMessage
import os

def Push_LINE_message():
    # 從環境變數或直接設定您的 Channel Access Token (CHANNEL_ACCESS_TOKEN)

    line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

    messages = [
        TextSendMessage(text="[Test] 這是由Scott送出的一則廣播訊息。")
    ]

    try:
        line_bot_api.broadcast(messages=messages)
        print("成功發送廣播訊息！")
        # line_bot_api.push_message(user_id, message)
    except Exception as e:
        print(f"發送廣播訊息失敗：{e}")

def send_LINE_message(line_msg):

    if (really_send_message == True):
        # 從環境變數或直接設定您的 Channel Access Token (CHANNEL_ACCESS_TOKEN)

        line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

        messages = [
            TextSendMessage(text=line_msg)
        ]

        try:
            line_bot_api.broadcast(messages=messages)
            print("成功發送LINE廣播訊息！")
            # line_bot_api.push_message(user_id, message)
        except Exception as e:
            print(f"發送LINE廣播訊息失敗：{e}")
            return False

    print(f"\n----------- << send_line_message >> -----------")
    print(f"line_msg = \n{line_msg}")


if __name__ == "__main__":
    example_send_email_locally()
    # example_send_email()
    # example_send_sms()
    # Push_LINE_message()