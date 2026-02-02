"""
Email service for sending booking confirmations and reminders.
Uses SMTP to send emails with configurable settings from the database.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from models import db, Booking, Settings


def get_smtp_connection():
    """Create and return an SMTP connection using settings from database"""
    if not Settings.get_bool('email_enabled'):
        return None

    server = Settings.get('smtp_server')
    port = Settings.get_int('smtp_port', 587)
    username = Settings.get('smtp_username')
    password = Settings.get('smtp_password')
    use_tls = Settings.get_bool('smtp_use_tls')

    if not server or not username:
        return None

    try:
        smtp = smtplib.SMTP(server, port)
        if use_tls:
            smtp.starttls()
        if password:
            smtp.login(username, password)
        return smtp
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to connect to SMTP: {e}")
        return None


def send_email(to_email, subject, html_body, text_body=None):
    """Send an email using configured SMTP settings"""
    if not Settings.get_bool('email_enabled'):
        print(f"[EMAIL] Email disabled - would send to {to_email}: {subject}")
        return False

    from_email = Settings.get('smtp_username')
    business_name = Settings.get('business_name', 'Booking System')

    # Create message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{business_name} <{from_email}>"
    msg['To'] = to_email

    # Add text and HTML parts
    if text_body:
        msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    # Send
    smtp = get_smtp_connection()
    if not smtp:
        print(f"[EMAIL] Could not connect to SMTP server")
        return False

    try:
        smtp.sendmail(from_email, to_email, msg.as_string())
        smtp.quit()
        print(f"[EMAIL] Sent to {to_email}: {subject}")
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send email: {e}")
        return False


def send_confirmation_email(booking):
    """Send booking confirmation email to customer"""
    if not Settings.get_bool('send_confirmation_email'):
        return False

    business_name = Settings.get('business_name', 'Our Studio')
    business_phone = Settings.get('business_phone', '')
    business_address = Settings.get('business_address', '')

    # Format date nicely
    booking_date_str = booking.booking_date.strftime('%A, %B %d, %Y')

    subject = f"Booking Confirmed - {booking.service.name} on {booking.booking_date.strftime('%d/%m/%Y')}"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #f5f1e8;
                margin: 0;
                padding: 0;
                background-color: #1a3a32;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #142b26;
            }}
            .header {{
                background-color: #142b26;
                padding: 30px 20px;
                text-align: center;
                border-bottom: 1px solid #a68b4b;
            }}
            .header h1 {{
                font-family: Georgia, serif;
                color: #c9a962;
                font-size: 28px;
                margin: 0 0 5px 0;
                letter-spacing: 3px;
                font-weight: normal;
            }}
            .header p {{
                color: #d4bc7c;
                margin: 0;
                font-size: 14px;
                letter-spacing: 1px;
            }}
            .content {{
                padding: 30px 25px;
                background-color: #1a3a32;
            }}
            .content p {{
                color: #f5f1e8;
                margin-bottom: 15px;
            }}
            .details {{
                background-color: rgba(201, 169, 98, 0.1);
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                border: 1px solid rgba(201, 169, 98, 0.3);
            }}
            .details table {{ width: 100%; border-collapse: collapse; }}
            .details td {{
                padding: 10px 0;
                border-bottom: 1px solid rgba(201, 169, 98, 0.2);
                color: #f5f1e8;
            }}
            .details td:first-child {{
                color: #d4bc7c;
                width: 40%;
            }}
            .details tr:last-child td {{
                border-bottom: none;
            }}
            .important {{
                background-color: rgba(201, 169, 98, 0.15);
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                border-left: 4px solid #c9a962;
            }}
            .important strong {{
                color: #c9a962;
                display: block;
                margin-bottom: 10px;
            }}
            .important ul {{
                margin: 0;
                padding-left: 20px;
                color: #f5f1e8;
            }}
            .important li {{
                margin-bottom: 8px;
            }}
            .important a {{
                color: #c9a962;
                font-weight: bold;
            }}
            .footer {{
                padding: 25px;
                text-align: center;
                background-color: #142b26;
                border-top: 1px solid rgba(201, 169, 98, 0.3);
            }}
            .footer p {{
                color: rgba(245, 241, 232, 0.6);
                font-size: 14px;
                margin: 5px 0;
            }}
            .footer .business-name {{
                color: #c9a962;
                font-family: Georgia, serif;
                font-size: 16px;
                letter-spacing: 2px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>WHITE THORN PIERCING</h1>
                <p>Booking Confirmed</p>
            </div>
            <div class="content">
                <p>Hi {booking.customer_name},</p>
                <p>Your appointment has been confirmed. Here are your booking details:</p>

                <div class="details">
                    <table>
                        <tr>
                            <td>Service:</td>
                            <td>{booking.service.name}</td>
                        </tr>
                        <tr>
                            <td>Date:</td>
                            <td>{booking_date_str}</td>
                        </tr>
                        <tr>
                            <td>Time:</td>
                            <td>{booking.booking_time} - {booking.end_time}</td>
                        </tr>
                        <tr>
                            <td>Duration:</td>
                            <td>{booking.service.duration_minutes} minutes</td>
                        </tr>
                        {f'<tr><td>Price:</td><td>£{booking.service.price:.2f}</td></tr>' if booking.service.price else ''}
                    </table>
                </div>

                <div class="important">
                    <strong>Important:</strong>
                    <ul>
                        <li>Please arrive 5-10 minutes before your appointment</li>
                        <li>Bring a valid government-issued ID</li>
                        <li>If you need to cancel or reschedule, please <a href="https://whitethornpiercing.co.uk/customer/login">log in to your account here</a></li>
                    </ul>
                </div>

                <p>If you have any questions, please don't hesitate to contact us.</p>
            </div>
            <div class="footer">
                <p class="business-name">{business_name}</p>
                {f'<p>{business_phone}</p>' if business_phone else ''}
                {f'<p>{business_address}</p>' if business_address else ''}
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
    Booking Confirmed!

    Hi {booking.customer_name},

    Your appointment has been confirmed.

    BOOKING DETAILS:
    - Service: {booking.service.name}
    - Date: {booking_date_str}
    - Time: {booking.booking_time} - {booking.end_time}
    - Duration: {booking.service.duration_minutes} minutes
    {f'- Price: £{booking.service.price:.2f}' if booking.service.price else ''}

    IMPORTANT:
    - Please arrive 5-10 minutes before your appointment
    - Bring a valid government-issued ID
    - If you need to cancel or reschedule, please log in to your account: https://whitethornpiercing.co.uk/customer/login

    {business_name}
    {business_phone}
    {business_address}
    """

    success = send_email(booking.customer_email, subject, html_body, text_body)

    if success:
        booking.confirmation_sent = True
        db.session.commit()

    return success


def send_reminder_email(booking):
    """Send appointment reminder email to customer"""
    if not Settings.get_bool('send_reminder_email'):
        return False

    business_name = Settings.get('business_name', 'Our Studio')
    business_phone = Settings.get('business_phone', '')
    business_address = Settings.get('business_address', '')

    # Format date nicely
    booking_date_str = booking.booking_date.strftime('%A, %B %d, %Y')

    subject = f"Reminder: Your appointment tomorrow - {booking.service.name}"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #f5f1e8;
                margin: 0;
                padding: 0;
                background-color: #1a3a32;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #142b26;
            }}
            .header {{
                background-color: #142b26;
                padding: 30px 20px;
                text-align: center;
                border-bottom: 1px solid #a68b4b;
            }}
            .header h1 {{
                font-family: Georgia, serif;
                color: #c9a962;
                font-size: 28px;
                margin: 0 0 5px 0;
                letter-spacing: 3px;
                font-weight: normal;
            }}
            .header p {{
                color: #d4bc7c;
                margin: 0;
                font-size: 14px;
                letter-spacing: 1px;
            }}
            .content {{
                padding: 30px 25px;
                background-color: #1a3a32;
            }}
            .content p {{
                color: #f5f1e8;
                margin-bottom: 15px;
            }}
            .details {{
                background-color: rgba(201, 169, 98, 0.1);
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                border: 1px solid rgba(201, 169, 98, 0.3);
            }}
            .details table {{ width: 100%; border-collapse: collapse; }}
            .details td {{
                padding: 10px 0;
                border-bottom: 1px solid rgba(201, 169, 98, 0.2);
                color: #f5f1e8;
            }}
            .details td:first-child {{
                color: #d4bc7c;
                width: 40%;
            }}
            .details tr:last-child td {{
                border-bottom: none;
            }}
            .reminder-box {{
                background-color: rgba(201, 169, 98, 0.15);
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                border-left: 4px solid #c9a962;
            }}
            .reminder-box strong {{
                color: #c9a962;
                display: block;
                margin-bottom: 10px;
            }}
            .reminder-box ul {{
                margin: 0;
                padding-left: 20px;
                color: #f5f1e8;
            }}
            .reminder-box li {{
                margin-bottom: 8px;
            }}
            .reschedule-link {{
                color: rgba(245, 241, 232, 0.7);
                font-size: 14px;
            }}
            .reschedule-link a {{
                color: #c9a962;
            }}
            .footer {{
                padding: 25px;
                text-align: center;
                background-color: #142b26;
                border-top: 1px solid rgba(201, 169, 98, 0.3);
            }}
            .footer p {{
                color: rgba(245, 241, 232, 0.6);
                font-size: 14px;
                margin: 5px 0;
            }}
            .footer .business-name {{
                color: #c9a962;
                font-family: Georgia, serif;
                font-size: 16px;
                letter-spacing: 2px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>WHITE THORN PIERCING</h1>
                <p>Appointment Reminder</p>
            </div>
            <div class="content">
                <p>Hi {booking.customer_name},</p>
                <p>This is a friendly reminder about your upcoming appointment:</p>

                <div class="details">
                    <table>
                        <tr>
                            <td>Service:</td>
                            <td>{booking.service.name}</td>
                        </tr>
                        <tr>
                            <td>Date:</td>
                            <td>{booking_date_str}</td>
                        </tr>
                        <tr>
                            <td>Time:</td>
                            <td>{booking.booking_time} - {booking.end_time}</td>
                        </tr>
                    </table>
                </div>

                <div class="reminder-box">
                    <strong>Don't forget:</strong>
                    <ul>
                        <li>Please arrive 5-10 minutes early</li>
                        <li>Bring a valid government-issued ID</li>
                    </ul>
                </div>

                <p>We look forward to seeing you!</p>

                <p class="reschedule-link">
                    Need to cancel or reschedule? Please <a href="https://whitethornpiercing.co.uk/customer/login">log in to your account here</a>.
                </p>
            </div>
            <div class="footer">
                <p class="business-name">{business_name}</p>
                {f'<p>{business_phone}</p>' if business_phone else ''}
                {f'<p>{business_address}</p>' if business_address else ''}
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
    Appointment Reminder

    Hi {booking.customer_name},

    This is a friendly reminder about your upcoming appointment:

    Service: {booking.service.name}
    Date: {booking_date_str}
    Time: {booking.booking_time} - {booking.end_time}

    Don't forget:
    - Please arrive 5-10 minutes early
    - Bring a valid government-issued ID

    We look forward to seeing you!

    Need to cancel or reschedule? Log in to your account: https://whitethornpiercing.co.uk/customer/login

    {business_name}
    {business_phone}
    {business_address}
    """

    success = send_email(booking.customer_email, subject, html_body, text_body)

    if success:
        booking.reminder_sent = True
        db.session.commit()

    return success


def send_reschedule_email(booking, old_date, old_time):
    """Send booking reschedule confirmation email to customer"""
    if not Settings.get_bool('send_confirmation_email'):
        return False

    business_name = Settings.get('business_name', 'Our Studio')
    business_phone = Settings.get('business_phone', '')
    business_address = Settings.get('business_address', '')

    # Format dates nicely
    old_date_str = old_date.strftime('%A, %B %d, %Y')
    new_date_str = booking.booking_date.strftime('%A, %B %d, %Y')

    subject = f"Appointment Rescheduled - {booking.service.name} on {booking.booking_date.strftime('%d/%m/%Y')}"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #f5f1e8;
                margin: 0;
                padding: 0;
                background-color: #1a3a32;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #142b26;
            }}
            .header {{
                background-color: #142b26;
                padding: 30px 20px;
                text-align: center;
                border-bottom: 1px solid #a68b4b;
            }}
            .header h1 {{
                font-family: Georgia, serif;
                color: #c9a962;
                font-size: 28px;
                margin: 0 0 5px 0;
                letter-spacing: 3px;
                font-weight: normal;
            }}
            .header p {{
                color: #d4bc7c;
                margin: 0;
                font-size: 14px;
                letter-spacing: 1px;
            }}
            .content {{
                padding: 30px 25px;
                background-color: #1a3a32;
            }}
            .content p {{
                color: #f5f1e8;
                margin-bottom: 15px;
            }}
            .change-summary {{
                display: flex;
                gap: 20px;
                margin: 25px 0;
            }}
            .change-box {{
                flex: 1;
                padding: 15px;
                border-radius: 8px;
                text-align: center;
            }}
            .change-box.old {{
                background-color: rgba(150, 150, 150, 0.1);
                border: 1px solid rgba(150, 150, 150, 0.3);
            }}
            .change-box.new {{
                background-color: rgba(201, 169, 98, 0.15);
                border: 1px solid rgba(201, 169, 98, 0.5);
            }}
            .change-label {{
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 1px;
                margin-bottom: 8px;
            }}
            .change-box.old .change-label {{
                color: #999;
            }}
            .change-box.new .change-label {{
                color: #c9a962;
            }}
            .change-value {{
                font-size: 16px;
                color: #f5f1e8;
            }}
            .change-box.old .change-value {{
                text-decoration: line-through;
                opacity: 0.6;
            }}
            .details {{
                background-color: rgba(201, 169, 98, 0.1);
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                border: 1px solid rgba(201, 169, 98, 0.3);
            }}
            .details table {{ width: 100%; border-collapse: collapse; }}
            .details td {{
                padding: 10px 0;
                border-bottom: 1px solid rgba(201, 169, 98, 0.2);
                color: #f5f1e8;
            }}
            .details td:first-child {{
                color: #d4bc7c;
                width: 40%;
            }}
            .details tr:last-child td {{
                border-bottom: none;
            }}
            .important {{
                background-color: rgba(201, 169, 98, 0.15);
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                border-left: 4px solid #c9a962;
            }}
            .important strong {{
                color: #c9a962;
                display: block;
                margin-bottom: 10px;
            }}
            .important ul {{
                margin: 0;
                padding-left: 20px;
                color: #f5f1e8;
            }}
            .important li {{
                margin-bottom: 8px;
            }}
            .important a {{
                color: #c9a962;
                font-weight: bold;
            }}
            .footer {{
                padding: 25px;
                text-align: center;
                background-color: #142b26;
                border-top: 1px solid rgba(201, 169, 98, 0.3);
            }}
            .footer p {{
                color: rgba(245, 241, 232, 0.6);
                font-size: 14px;
                margin: 5px 0;
            }}
            .footer .business-name {{
                color: #c9a962;
                font-family: Georgia, serif;
                font-size: 16px;
                letter-spacing: 2px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>WHITE THORN PIERCING</h1>
                <p>Appointment Rescheduled</p>
            </div>
            <div class="content">
                <p>Hi {booking.customer_name},</p>
                <p>Your appointment has been successfully rescheduled. Here are your updated booking details:</p>

                <table width="100%" cellpadding="0" cellspacing="0" style="margin: 25px 0;">
                    <tr>
                        <td width="48%" style="padding: 15px; background-color: rgba(150, 150, 150, 0.1); border: 1px solid rgba(150, 150, 150, 0.3); border-radius: 8px; text-align: center;">
                            <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #999; margin-bottom: 8px;">Previous</div>
                            <div style="font-size: 16px; color: #f5f1e8; text-decoration: line-through; opacity: 0.6;">{old_date_str}<br>{old_time}</div>
                        </td>
                        <td width="4%" style="text-align: center; color: #c9a962; font-size: 24px;">&rarr;</td>
                        <td width="48%" style="padding: 15px; background-color: rgba(201, 169, 98, 0.15); border: 1px solid rgba(201, 169, 98, 0.5); border-radius: 8px; text-align: center;">
                            <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #c9a962; margin-bottom: 8px;">New</div>
                            <div style="font-size: 16px; color: #f5f1e8;">{new_date_str}<br>{booking.booking_time}</div>
                        </td>
                    </tr>
                </table>

                <div class="details">
                    <table>
                        <tr>
                            <td>Service:</td>
                            <td>{booking.service.name}</td>
                        </tr>
                        <tr>
                            <td>New Date:</td>
                            <td>{new_date_str}</td>
                        </tr>
                        <tr>
                            <td>New Time:</td>
                            <td>{booking.booking_time} - {booking.end_time}</td>
                        </tr>
                        <tr>
                            <td>Duration:</td>
                            <td>{booking.service.duration_minutes} minutes</td>
                        </tr>
                        {f'<tr><td>Price:</td><td>£{booking.service.price:.2f}</td></tr>' if booking.service.price else ''}
                    </table>
                </div>

                <div class="important">
                    <strong>Important:</strong>
                    <ul>
                        <li>Please arrive 5-10 minutes before your appointment</li>
                        <li>Bring a valid government-issued ID</li>
                        <li>If you need to cancel or reschedule again, please <a href="https://whitethornpiercing.co.uk/customer/login">log in to your account here</a></li>
                    </ul>
                </div>

                <p>If you have any questions, please don't hesitate to contact us.</p>
            </div>
            <div class="footer">
                <p class="business-name">{business_name}</p>
                {f'<p>{business_phone}</p>' if business_phone else ''}
                {f'<p>{business_address}</p>' if business_address else ''}
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
    Appointment Rescheduled

    Hi {booking.customer_name},

    Your appointment has been successfully rescheduled.

    PREVIOUS APPOINTMENT:
    - Date: {old_date_str}
    - Time: {old_time}

    NEW APPOINTMENT:
    - Service: {booking.service.name}
    - Date: {new_date_str}
    - Time: {booking.booking_time} - {booking.end_time}
    - Duration: {booking.service.duration_minutes} minutes
    {f'- Price: £{booking.service.price:.2f}' if booking.service.price else ''}

    IMPORTANT:
    - Please arrive 5-10 minutes before your appointment
    - Bring a valid government-issued ID
    - If you need to cancel or reschedule again, please log in to your account: https://whitethornpiercing.co.uk/customer/login

    {business_name}
    {business_phone}
    {business_address}
    """

    return send_email(booking.customer_email, subject, html_body, text_body)


def send_followup_email(booking):
    """Send 6-week follow-up email for aftercare and downsize reminder"""
    business_name = Settings.get('business_name', 'Our Studio')
    business_phone = Settings.get('business_phone', '')
    business_address = Settings.get('business_address', '')

    subject = f"6 Week Check-in: Time for Your Downsize! - {booking.service.name}"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #f5f1e8;
                margin: 0;
                padding: 0;
                background-color: #1a3a32;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #142b26;
            }}
            .header {{
                background-color: #142b26;
                padding: 30px 20px;
                text-align: center;
                border-bottom: 1px solid #a68b4b;
            }}
            .header h1 {{
                font-family: Georgia, serif;
                color: #c9a962;
                font-size: 28px;
                margin: 0 0 5px 0;
                letter-spacing: 3px;
                font-weight: normal;
            }}
            .header p {{
                color: #d4bc7c;
                margin: 0;
                font-size: 14px;
                letter-spacing: 1px;
            }}
            .content {{
                padding: 30px 25px;
                background-color: #1a3a32;
            }}
            .content p {{
                color: #f5f1e8;
                margin-bottom: 15px;
            }}
            .tip-box {{
                background-color: rgba(201, 169, 98, 0.1);
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                border: 1px solid rgba(201, 169, 98, 0.3);
            }}
            .tip-box h3 {{
                color: #c9a962;
                margin: 0 0 10px 0;
                font-size: 18px;
            }}
            .tip-box p {{
                margin: 0;
                color: #f5f1e8;
            }}
            .cta-box {{
                background-color: rgba(201, 169, 98, 0.15);
                padding: 25px;
                border-radius: 8px;
                margin: 25px 0;
                text-align: center;
                border: 1px solid rgba(201, 169, 98, 0.5);
            }}
            .cta-box p {{
                margin: 0 0 15px 0;
                color: #f5f1e8;
            }}
            .cta-button {{
                display: inline-block;
                background-color: #c9a962;
                color: #142b26;
                padding: 12px 30px;
                text-decoration: none;
                border-radius: 5px;
                font-weight: bold;
                letter-spacing: 1px;
            }}
            .footer {{
                padding: 25px;
                text-align: center;
                background-color: #142b26;
                border-top: 1px solid rgba(201, 169, 98, 0.3);
            }}
            .footer p {{
                color: rgba(245, 241, 232, 0.6);
                font-size: 14px;
                margin: 5px 0;
            }}
            .footer .business-name {{
                color: #c9a962;
                font-family: Georgia, serif;
                font-size: 16px;
                letter-spacing: 2px;
            }}
            .signoff {{
                color: #c9a962;
                font-style: italic;
                margin-top: 25px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>WHITE THORN PIERCING</h1>
                <p>6 Week Check-in</p>
            </div>
            <div class="content">
                <p>Hi {booking.customer_name},</p>

                <p>It's been about six weeks since your piercing appointment! By now, the initial swelling has likely gone down, and you're hopefully loving your new look.</p>

                <p>Since you've reached this milestone, there are three things we recommend to keep your piercing healthy and looking its best:</p>

                <div class="tip-box">
                    <h3>1. The "Downsize" (Crucial Step!)</h3>
                    <p>When we first pierced you, we used a slightly longer bar to allow for natural swelling. Now that the swelling is gone, that extra length can actually cause irritation or even cause the piercing to heal at an angle if it gets snagged. It's time to swap to a shorter, "downsized" post for a snugger, safer fit.</p>
                </div>

                <div class="tip-box">
                    <h3>2. Check Your Aftercare</h3>
                    <p>Even if it feels "healed" on the outside, the internal tissue is still working hard. Continue with your saline rinses and try your best not to sleep on it or touch it with unwashed hands. Consistency now prevents "the bump" later!</p>
                </div>

                <div class="tip-box">
                    <h3>3. Fresh Sparkle?</h3>
                    <p>If you're looking to celebrate your healing progress, we have some beautiful new jewellery pieces in stock that would look perfect in your collection.</p>
                </div>

                <div class="cta-box">
                    <p>Want to pop in? Click below to book a quick <strong>"Downsize & Check-up"</strong> appointment. We'll make sure everything is healing perfectly and get your jewellery fitted correctly.</p>
                    <a href="https://whitethornpiercing.co.uk/customer/login" class="cta-button">BOOK YOUR CHECK-UP</a>
                </div>

                <p class="signoff">Stay sparkly,<br>The White Thorn Piercing Team</p>
            </div>
            <div class="footer">
                <p class="business-name">{business_name}</p>
                {f'<p>{business_phone}</p>' if business_phone else ''}
                {f'<p>{business_address}</p>' if business_address else ''}
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
    6 Week Check-in: Time for Your Downsize!

    Hi {booking.customer_name},

    It's been about six weeks since your piercing appointment! By now, the initial swelling has likely gone down, and you're hopefully loving your new look.

    Since you've reached this milestone, there are three things we recommend to keep your piercing healthy and looking its best:

    1. THE "DOWNSIZE" (CRUCIAL STEP!)
    When we first pierced you, we used a slightly longer bar to allow for natural swelling. Now that the swelling is gone, that extra length can actually cause irritation or even cause the piercing to heal at an angle if it gets snagged. It's time to swap to a shorter, "downsized" post for a snugger, safer fit.

    2. CHECK YOUR AFTERCARE
    Even if it feels "healed" on the outside, the internal tissue is still working hard. Continue with your saline rinses and try your best not to sleep on it or touch it with unwashed hands. Consistency now prevents "the bump" later!

    3. FRESH SPARKLE?
    If you're looking to celebrate your healing progress, we have some beautiful new jewellery pieces in stock that would look perfect in your collection.

    BOOK YOUR CHECK-UP
    Want to pop in? Log in to your account to book a quick "Downsize & Check-up" appointment:
    https://whitethornpiercing.co.uk/customer/login

    We'll make sure everything is healing perfectly and get your jewellery fitted correctly.

    Stay sparkly,
    The White Thorn Piercing Team

    {business_name}
    {business_phone}
    {business_address}
    """

    success = send_email(booking.customer_email, subject, html_body, text_body)

    if success:
        booking.followup_sent = True
        db.session.commit()

    return success


def check_and_send_followups(app):
    """
    Check for completed bookings that are 6 weeks old and send follow-up emails.
    Should be called periodically (e.g., daily).
    """
    with app.app_context():
        if not Settings.get_bool('email_enabled'):
            return

        # Check if follow-up emails are enabled (default to True)
        if not Settings.get_bool('send_followup_email', True):
            return

        # Calculate 6 weeks ago (42 days)
        now = datetime.now()
        six_weeks_ago = now - timedelta(days=42)
        # Give a 3-day window to catch any missed ones
        window_start = six_weeks_ago - timedelta(days=3)

        # Find bookings that:
        # 1. Are completed (NOT no_show or cancelled)
        # 2. Haven't had a follow-up sent
        # 3. Were completed around 6 weeks ago
        bookings = Booking.query.filter(
            Booking.status == 'completed',  # Only completed, excludes no_show and cancelled
            Booking.followup_sent == False,
            Booking.booking_date <= six_weeks_ago.date(),
            Booking.booking_date >= window_start.date()
        ).all()

        for booking in bookings:
            print(f"[FOLLOWUP] Sending 6-week follow-up for booking {booking.id} ({booking.customer_name})")
            send_followup_email(booking)


def send_day_after_email(booking):
    """Send 24-hour follow-up email for review request and aftercare check"""
    business_name = Settings.get('business_name', 'White Thorn Piercing')
    business_phone = Settings.get('business_phone', '')
    business_address = Settings.get('business_address', '')
    google_review_link = Settings.get('google_review_link', 'https://g.page/r/YOUR_REVIEW_LINK')

    subject = f"How's your new piercing feeling? - {booking.service.name}"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #f5f1e8;
                margin: 0;
                padding: 0;
                background-color: #1a3a32;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #142b26;
            }}
            .header {{
                background-color: #142b26;
                padding: 30px 20px;
                text-align: center;
                border-bottom: 1px solid #a68b4b;
            }}
            .header h1 {{
                font-family: Georgia, serif;
                color: #c9a962;
                font-size: 28px;
                margin: 0 0 5px 0;
                letter-spacing: 3px;
                font-weight: normal;
            }}
            .header p {{
                color: #d4bc7c;
                margin: 0;
                font-size: 14px;
                letter-spacing: 1px;
            }}
            .content {{
                padding: 30px 25px;
                background-color: #1a3a32;
            }}
            .content p {{
                color: #f5f1e8;
                margin-bottom: 15px;
            }}
            .aftercare-reminder {{
                background-color: rgba(201, 169, 98, 0.1);
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                border: 1px solid rgba(201, 169, 98, 0.3);
                text-align: center;
            }}
            .aftercare-reminder p {{
                margin: 0;
                font-size: 18px;
                color: #c9a962;
                font-weight: bold;
            }}
            .review-box {{
                background-color: rgba(201, 169, 98, 0.15);
                padding: 25px;
                border-radius: 8px;
                margin: 25px 0;
                border: 1px solid rgba(201, 169, 98, 0.5);
            }}
            .review-box h3 {{
                color: #c9a962;
                margin: 0 0 15px 0;
            }}
            .review-box p {{
                margin: 0 0 15px 0;
                color: #f5f1e8;
            }}
            .cta-button {{
                display: inline-block;
                background-color: #c9a962;
                color: #142b26;
                padding: 12px 30px;
                text-decoration: none;
                border-radius: 5px;
                font-weight: bold;
                letter-spacing: 1px;
            }}
            .help-text {{
                background-color: rgba(100, 100, 100, 0.1);
                padding: 15px;
                border-radius: 8px;
                margin: 20px 0;
                border-left: 4px solid #c9a962;
            }}
            .help-text p {{
                margin: 0;
                color: #f5f1e8;
                font-size: 14px;
            }}
            .footer {{
                padding: 25px;
                text-align: center;
                background-color: #142b26;
                border-top: 1px solid rgba(201, 169, 98, 0.3);
            }}
            .footer p {{
                color: rgba(245, 241, 232, 0.6);
                font-size: 14px;
                margin: 5px 0;
            }}
            .footer .business-name {{
                color: #c9a962;
                font-family: Georgia, serif;
                font-size: 16px;
                letter-spacing: 2px;
            }}
            .signoff {{
                color: #c9a962;
                font-style: italic;
                margin-top: 25px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>WHITE THORN PIERCING</h1>
                <p>Thank You!</p>
            </div>
            <div class="content">
                <p>Hi {booking.customer_name},</p>

                <p>Thank you so much for visiting us yesterday! It was a pleasure helping you with your new {booking.service.name.split('£')[0].strip()}.</p>

                <p>I wanted to send a quick note to make sure you're feeling great. The first 24 hours are the most important for starting your aftercare routine, so remember:</p>

                <div class="aftercare-reminder">
                    <p>Clean, dry, and don't touch!</p>
                </div>

                <div class="review-box">
                    <h3>Could you do me a huge favour?</h3>
                    <p>As a small business, word-of-mouth is everything. If you enjoyed your experience and love your new jewellery, would you mind taking 30 seconds to leave a quick review on Google?</p>
                    <p>It helps others find us and truly means the world to me.</p>
                    <p style="text-align: center; margin-top: 20px;">
                        <a href="{google_review_link}" class="cta-button">LEAVE A REVIEW ⭐</a>
                    </p>
                </div>

                <div class="help-text">
                    <p>If you have any questions or if anything feels off, just reply to this email—I'm here to help!</p>
                </div>

                <p class="signoff">Happy healing,<br>The White Thorn Piercing Team</p>
            </div>
            <div class="footer">
                <p class="business-name">{business_name}</p>
                {f'<p>{business_phone}</p>' if business_phone else ''}
                {f'<p>{business_address}</p>' if business_address else ''}
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
    How's your new piercing feeling?

    Hi {booking.customer_name},

    Thank you so much for visiting us yesterday! It was a pleasure helping you with your new {booking.service.name.split('£')[0].strip()}.

    I wanted to send a quick note to make sure you're feeling great. The first 24 hours are the most important for starting your aftercare routine, so remember:

    CLEAN, DRY, AND DON'T TOUCH!

    ---

    COULD YOU DO ME A HUGE FAVOUR?

    As a small business, word-of-mouth is everything. If you enjoyed your experience and love your new jewellery, would you mind taking 30 seconds to leave a quick review on Google?

    It helps others find us and truly means the world to me.

    Leave a review here: {google_review_link}

    ---

    If you have any questions or if anything feels off, just reply to this email—I'm here to help!

    Happy healing,
    The White Thorn Piercing Team

    {business_name}
    {business_phone}
    {business_address}
    """

    success = send_email(booking.customer_email, subject, html_body, text_body)

    if success:
        booking.day_after_sent = True
        db.session.commit()

    return success


def check_and_send_day_after_emails(app):
    """
    Check for completed bookings from yesterday and send 24-hour follow-up emails.
    Should be called periodically (e.g., every hour).
    """
    with app.app_context():
        if not Settings.get_bool('email_enabled'):
            return

        # Check if 24hr follow-up emails are enabled (default to True)
        if not Settings.get_bool('send_day_after_email', True):
            return

        # Calculate yesterday's date range
        now = datetime.now()
        yesterday = now - timedelta(days=1)
        yesterday_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)

        # Find bookings that:
        # 1. Are completed (appointment happened)
        # 2. Haven't had a day-after email sent
        # 3. Are not blocked from receiving this email
        # 4. Were completed yesterday
        bookings = Booking.query.filter(
            Booking.status == 'completed',
            Booking.day_after_sent == False,
            Booking.day_after_blocked == False,
            Booking.booking_date == yesterday.date()
        ).all()

        for booking in bookings:
            print(f"[DAY-AFTER] Sending 24hr follow-up for booking {booking.id} ({booking.customer_name})")
            send_day_after_email(booking)


def check_and_send_reminders(app):
    """
    Check for upcoming bookings and send reminders.
    Should be called periodically (e.g., every hour).
    """
    with app.app_context():
        if not Settings.get_bool('email_enabled') or not Settings.get_bool('send_reminder_email'):
            return

        hours_before = Settings.get_int('reminder_hours_before', 24)

        # Calculate the window for sending reminders
        now = datetime.now()
        reminder_threshold = now + timedelta(hours=hours_before)

        # Find bookings that:
        # 1. Are confirmed
        # 2. Haven't had a reminder sent
        # 3. Are within the reminder window
        bookings = Booking.query.filter(
            Booking.status == 'confirmed',
            Booking.reminder_sent == False,
            Booking.booking_date <= reminder_threshold.date()
        ).all()

        for booking in bookings:
            # Calculate exact datetime of booking
            booking_datetime = datetime.combine(
                booking.booking_date,
                datetime.strptime(booking.booking_time, '%H:%M').time()
            )

            # Only send if within the reminder window
            time_until_booking = booking_datetime - now
            if timedelta(0) < time_until_booking <= timedelta(hours=hours_before):
                print(f"[REMINDER] Sending reminder for booking {booking.id} ({booking.customer_name})")
                send_reminder_email(booking)


def send_test_email(to_email):
    """Send a test email to verify SMTP settings"""
    business_name = Settings.get('business_name', 'Booking System')

    subject = "Test Email - White Thorn Piercing"
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #f5f1e8;
                margin: 0;
                padding: 0;
                background-color: #1a3a32;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #142b26;
            }}
            .header {{
                background-color: #142b26;
                padding: 30px 20px;
                text-align: center;
                border-bottom: 1px solid #a68b4b;
            }}
            .header h1 {{
                font-family: Georgia, serif;
                color: #c9a962;
                font-size: 28px;
                margin: 0;
                letter-spacing: 3px;
                font-weight: normal;
            }}
            .content {{
                padding: 30px 25px;
                background-color: #1a3a32;
            }}
            .success {{
                background-color: rgba(201, 169, 98, 0.15);
                padding: 20px;
                border-radius: 8px;
                border-left: 4px solid #c9a962;
            }}
            .success h2 {{
                color: #c9a962;
                margin-top: 0;
            }}
            .success p {{
                color: #f5f1e8;
                margin: 10px 0;
            }}
            .footer {{
                padding: 25px;
                text-align: center;
                background-color: #142b26;
                border-top: 1px solid rgba(201, 169, 98, 0.3);
            }}
            .footer p {{
                color: rgba(245, 241, 232, 0.6);
                font-size: 14px;
                margin: 5px 0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>WHITE THORN PIERCING</h1>
            </div>
            <div class="content">
                <div class="success">
                    <h2>Email Configuration Successful!</h2>
                    <p>If you're reading this, your email settings are working correctly.</p>
                    <p>Sent from: {business_name}</p>
                    <p>Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
            </div>
            <div class="footer">
                <p>This is a test email from your booking system.</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
    Email Configuration Successful!

    If you're reading this, your email settings are working correctly.

    Sent from: {business_name}
    Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """

    return send_email(to_email, subject, html_body, text_body)
