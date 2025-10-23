#!/usr/bin/env python3
"""
ZeroQue Notifications Service - Streamlit Demo
Notification management and delivery
"""

import streamlit as st
import requests
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List

# Page configuration
st.set_page_config(
    page_title="ZeroQue Notifications Service",
    page_icon="📧",
    layout="wide"
)

# Service configuration
SERVICE_PORT = 8222
BASE_URL = f"http://localhost:{SERVICE_PORT}"

# Test data
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440001"
TEST_SITE_ID = "550e8400-e29b-41d4-a716-446655440002"
TEST_STORE_ID = "550e8400-e29b-41d4-a716-446655440003"

def make_request(endpoint: str, method: str = "GET", data: Dict = None) -> Dict[str, Any]:
    """Make API request"""
    try:
        url = f"{BASE_URL}{endpoint}"
        
        if method == "GET":
            response = requests.get(url, timeout=10)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=10)
        elif method == "PUT":
            response = requests.put(url, json=data, timeout=10)
        elif method == "DELETE":
            response = requests.delete(url, timeout=10)
        else:
            return {"error": f"Unsupported method: {method}"}
        
        return {
            "status_code": response.status_code,
            "data": response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
            "success": response.status_code < 400
        }
    except Exception as e:
        return {"error": str(e), "success": False}

def main():
    """Main application"""
    st.title("📧 ZeroQue Notifications Service")
    st.markdown("Notification management and delivery")
    
    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.selectbox(
        "Select Page",
        ["Dashboard", "Send Notification", "Notification List", "Notification Details", "Analytics"]
    )
    
    # Initialize session state
    if "tenant_id" not in st.session_state:
        st.session_state.tenant_id = TEST_TENANT_ID
    if "user_id" not in st.session_state:
        st.session_state.user_id = TEST_USER_ID
    if "site_id" not in st.session_state:
        st.session_state.site_id = TEST_SITE_ID
    if "store_id" not in st.session_state:
        st.session_state.store_id = TEST_STORE_ID
    
    # Route to selected page
    if page == "Dashboard":
        show_dashboard()
    elif page == "Send Notification":
        show_send_notification()
    elif page == "Notification List":
        show_notification_list()
    elif page == "Notification Details":
        show_notification_details()
    elif page == "Analytics":
        show_analytics()

def show_dashboard():
    """Dashboard page"""
    st.header("📊 Notifications Dashboard")
    
    # Service health
    st.subheader("Service Health")
    health_result = make_request("/health")
    
    if health_result["success"]:
        st.success("✅ Service is healthy")
        st.json(health_result["data"])
    else:
        st.error(f"❌ Service is unhealthy: {health_result.get('error', 'Unknown error')}")
    
    # Quick stats
    st.subheader("Quick Statistics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Notifications", "15,678", "567")
    
    with col2:
        st.metric("Delivered", "14,890", "523")
    
    with col3:
        st.metric("Pending", "456", "23")
    
    with col4:
        st.metric("Failed", "332", "21")
    
    # Notification status distribution
    st.subheader("Notification Status Distribution")
    
    # Sample notification status data
    status_data = [
        {"status": "pending", "count": 456, "percentage": 2.9},
        {"status": "sent", "count": 1234, "percentage": 7.9},
        {"status": "delivered", "count": 14890, "percentage": 95.0},
        {"status": "failed", "count": 332, "percentage": 2.1},
        {"status": "bounced", "count": 123, "percentage": 0.8},
        {"status": "complained", "count": 45, "percentage": 0.3}
    ]
    
    import pandas as pd
    import plotly.express as px
    
    df = pd.DataFrame(status_data)
    fig = px.pie(df, values="count", names="status", title="Notification Status Distribution")
    st.plotly_chart(fig, use_container_width=True)
    
    # Recent notifications
    st.subheader("Recent Notifications")
    
    # Sample recent notifications
    recent_notifications = [
        {"notification_id": "NOT-001", "recipient": "john@example.com", "type": "email", "status": "delivered", "subject": "Order Confirmation", "timestamp": "2024-01-15 10:30:00"},
        {"notification_id": "NOT-002", "recipient": "+1234567890", "type": "sms", "status": "sent", "subject": "Payment Reminder", "timestamp": "2024-01-15 09:45:00"},
        {"notification_id": "NOT-003", "recipient": "jane@example.com", "type": "email", "status": "delivered", "subject": "Invoice Ready", "timestamp": "2024-01-15 08:20:00"},
        {"notification_id": "NOT-004", "recipient": "bob@example.com", "type": "email", "status": "failed", "subject": "Welcome Email", "timestamp": "2024-01-15 07:15:00"},
        {"notification_id": "NOT-005", "recipient": "+0987654321", "type": "sms", "status": "delivered", "subject": "Delivery Update", "timestamp": "2024-01-15 06:30:00"}
    ]
    
    for notification in recent_notifications:
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        
        with col1:
            st.write(f"**{notification['notification_id']}**")
        
        with col2:
            st.write(notification['recipient'])
        
        with col3:
            if notification['type'] == 'email':
                st.info(notification['type'])
            else:
                st.success(notification['type'])
        
        with col4:
            if notification['status'] == 'delivered':
                st.success(notification['status'])
            elif notification['status'] == 'sent':
                st.info(notification['status'])
            elif notification['status'] == 'failed':
                st.error(notification['status'])
            else:
                st.write(notification['status'])
        
        with col5:
            st.write(notification['subject'])
        
        with col6:
            st.write(notification['timestamp'])

def show_send_notification():
    """Send notification page"""
    st.header("📧 Send New Notification")
    
    with st.form("send_notification"):
        # Notification basic information
        st.subheader("Notification Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            notification_type = st.selectbox("Notification Type", ["email", "sms", "push", "webhook"])
            priority = st.selectbox("Priority", ["low", "normal", "high", "urgent"])
            template_id = st.text_input("Template ID", value="welcome_email")
            subject = st.text_input("Subject", value="Demo Notification")
        
        with col2:
            recipient_email = st.text_input("Recipient Email", value="demo@example.com")
            recipient_phone = st.text_input("Recipient Phone", value="+1234567890")
            recipient_name = st.text_input("Recipient Name", value="Demo User")
            language = st.selectbox("Language", ["en", "es", "fr", "de"])
        
        # Notification content
        st.subheader("Notification Content")
        
        # Email content
        if notification_type == "email":
            html_content = st.text_area(
                "HTML Content",
                value="<h1>Welcome!</h1><p>This is a demo notification.</p>",
                height=200
            )
            text_content = st.text_area(
                "Text Content",
                value="Welcome! This is a demo notification.",
                height=100
            )
        
        # SMS content
        elif notification_type == "sms":
            sms_content = st.text_area(
                "SMS Content",
                value="Welcome! This is a demo SMS notification.",
                height=100,
                max_chars=160
            )
        
        # Push notification content
        elif notification_type == "push":
            push_title = st.text_input("Push Title", value="Demo Push Notification")
            push_body = st.text_area(
                "Push Body",
                value="This is a demo push notification.",
                height=100
            )
            push_data = st.text_area(
                "Push Data (JSON)",
                value='{"action": "open_app", "screen": "home"}',
                height=100
            )
        
        # Webhook content
        elif notification_type == "webhook":
            webhook_url = st.text_input("Webhook URL", value="https://example.com/webhook")
            webhook_data = st.text_area(
                "Webhook Data (JSON)",
                value='{"event": "notification", "data": {"message": "Demo notification"}}',
                height=150
            )
        
        # Delivery options
        st.subheader("Delivery Options")
        
        col1, col2 = st.columns(2)
        
        with col1:
            send_immediately = st.checkbox("Send Immediately", value=True)
            schedule_time = st.datetime_input("Schedule Time", value=datetime.now())
            retry_attempts = st.number_input("Retry Attempts", min_value=0, max_value=5, value=3)
            retry_interval = st.number_input("Retry Interval (minutes)", min_value=1, max_value=60, value=5)
        
        with col2:
            track_opens = st.checkbox("Track Opens", value=True)
            track_clicks = st.checkbox("Track Clicks", value=True)
            unsubscribe_link = st.checkbox("Include Unsubscribe Link", value=True)
            reply_to = st.text_input("Reply To", value="noreply@example.com")
        
        # Additional data
        st.subheader("Additional Data")
        
        metadata = st.text_area(
            "Metadata (JSON)",
            value='{"campaign": "demo", "source": "streamlit"}',
            height=100
        )
        
        if st.form_submit_button("Send Notification"):
            try:
                notification_data = {
                    "tenant_id": st.session_state.tenant_id,
                    "site_id": st.session_state.site_id,
                    "store_id": st.session_state.store_id,
                    "user_id": st.session_state.user_id,
                    "notification_type": notification_type,
                    "priority": priority,
                    "template_id": template_id,
                    "subject": subject,
                    "recipient_email": recipient_email,
                    "recipient_phone": recipient_phone,
                    "recipient_name": recipient_name,
                    "language": language,
                    "send_immediately": send_immediately,
                    "schedule_time": schedule_time.isoformat() if not send_immediately else None,
                    "retry_attempts": retry_attempts,
                    "retry_interval": retry_interval,
                    "track_opens": track_opens,
                    "track_clicks": track_clicks,
                    "unsubscribe_link": unsubscribe_link,
                    "reply_to": reply_to,
                    "metadata": json.loads(metadata)
                }
                
                # Add type-specific content
                if notification_type == "email":
                    notification_data["html_content"] = html_content
                    notification_data["text_content"] = text_content
                elif notification_type == "sms":
                    notification_data["sms_content"] = sms_content
                elif notification_type == "push":
                    notification_data["push_title"] = push_title
                    notification_data["push_body"] = push_body
                    notification_data["push_data"] = json.loads(push_data)
                elif notification_type == "webhook":
                    notification_data["webhook_url"] = webhook_url
                    notification_data["webhook_data"] = json.loads(webhook_data)
                
                result = make_request("/notifications/new", "POST", notification_data)
                
                if result["success"]:
                    st.success("✅ Notification sent successfully!")
                    st.json(result["data"])
                else:
                    st.error(f"❌ Failed to send notification: {result.get('error', 'Unknown error')}")
            except json.JSONDecodeError:
                st.error("❌ Invalid JSON in metadata or push data")
    
    # Notification templates
    st.subheader("Notification Templates")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("Welcome Email Template", use_container_width=True):
            st.info("Welcome email template loaded")
    
    with col2:
        if st.button("Order Confirmation Template", use_container_width=True):
            st.info("Order confirmation template loaded")
    
    with col3:
        if st.button("Payment Reminder Template", use_container_width=True):
            st.info("Payment reminder template loaded")

def show_notification_list():
    """Notification list page"""
    st.header("📋 Notification List")
    
    # Filters
    st.subheader("Filters")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        status_filter = st.selectbox("Status", ["All", "pending", "sent", "delivered", "failed", "bounced", "complained"])
    
    with col2:
        type_filter = st.selectbox("Notification Type", ["All", "email", "sms", "push", "webhook"])
    
    with col3:
        priority_filter = st.selectbox("Priority", ["All", "low", "normal", "high", "urgent"])
    
    with col4:
        date_range = st.date_input("Date Range", value=[datetime.now().date(), datetime.now().date()])
    
    # Search
    search_query = st.text_input("Search Notifications", placeholder="Notification ID, recipient, or subject")
    
    # Get notifications
    if st.button("Get Notifications"):
        result = make_request("/notifications/new", "GET")
        
        if result["success"]:
            notifications = result["data"]
            if notifications:
                st.success(f"✅ Found {len(notifications)} notifications")
                
                # Display notifications in a table
                for notification in notifications:
                    with st.expander(f"Notification: {notification.get('notification_id', 'Unknown')}"):
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.write(f"**Recipient:** {notification.get('recipient_email', notification.get('recipient_phone', 'N/A'))}")
                            st.write(f"**Type:** {notification.get('notification_type', 'N/A')}")
                            st.write(f"**Priority:** {notification.get('priority', 'N/A')}")
                        
                        with col2:
                            st.write(f"**Status:** {notification.get('status', 'N/A')}")
                            st.write(f"**Subject:** {notification.get('subject', 'N/A')}")
                            st.write(f"**Template:** {notification.get('template_id', 'N/A')}")
                        
                        with col3:
                            st.write(f"**Created:** {notification.get('created_at', 'N/A')}")
                            st.write(f"**Sent:** {notification.get('sent_at', 'N/A')}")
                            st.write(f"**Delivered:** {notification.get('delivered_at', 'N/A')}")
                        
                        # Notification actions
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            if st.button("View Details", key=f"view_{notification.get('notification_id', 'unknown')}"):
                                st.info("Notification details would be displayed here")
                        
                        with col2:
                            if st.button("Resend", key=f"resend_{notification.get('notification_id', 'unknown')}"):
                                st.info("Notification resending would be processed here")
                        
                        with col3:
                            if st.button("Track Opens", key=f"track_{notification.get('notification_id', 'unknown')}"):
                                st.info("Open tracking would be displayed here")
                        
                        with col4:
                            if st.button("View Logs", key=f"logs_{notification.get('notification_id', 'unknown')}"):
                                st.info("Notification logs would be displayed here")
            else:
                st.info("No notifications found")
        else:
            st.error(f"❌ Failed to get notifications: {result.get('error', 'Unknown error')}")
    
    # Notification actions
    st.subheader("Bulk Actions")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("Export Notifications", use_container_width=True):
            st.info("Notifications export initiated")
    
    with col2:
        if st.button("Resend Failed", use_container_width=True):
            st.info("Failed notifications resending initiated")
    
    with col3:
        if st.button("Generate Reports", use_container_width=True):
            st.info("Report generation initiated")
    
    with col4:
        if st.button("Cleanup Old", use_container_width=True):
            st.info("Old notifications cleanup initiated")

def show_notification_details():
    """Notification details page"""
    st.header("📄 Notification Details")
    
    # Notification ID input
    notification_id = st.text_input("Notification ID", placeholder="Enter notification ID to view details")
    
    if notification_id and st.button("Get Notification Details"):
        result = make_request(f"/notifications/new/{notification_id}", "GET")
        
        if result["success"]:
            notification = result["data"]
            st.success("✅ Notification details retrieved!")
            
            # Notification information
            st.subheader("Notification Information")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**Notification ID:** {notification.get('notification_id', 'N/A')}")
                st.write(f"**Recipient:** {notification.get('recipient_email', notification.get('recipient_phone', 'N/A'))}")
                st.write(f"**Type:** {notification.get('notification_type', 'N/A')}")
                st.write(f"**Priority:** {notification.get('priority', 'N/A')}")
                st.write(f"**Status:** {notification.get('status', 'N/A')}")
            
            with col2:
                st.write(f"**Subject:** {notification.get('subject', 'N/A')}")
                st.write(f"**Template:** {notification.get('template_id', 'N/A')}")
                st.write(f"**Language:** {notification.get('language', 'N/A')}")
                st.write(f"**Created:** {notification.get('created_at', 'N/A')}")
                st.write(f"**Sent:** {notification.get('sent_at', 'N/A')}")
            
            # Notification content
            st.subheader("Notification Content")
            
            if notification.get('notification_type') == 'email':
                if notification.get('html_content'):
                    st.write("**HTML Content:**")
                    st.code(notification['html_content'], language='html')
                
                if notification.get('text_content'):
                    st.write("**Text Content:**")
                    st.code(notification['text_content'])
            
            elif notification.get('notification_type') == 'sms':
                if notification.get('sms_content'):
                    st.write("**SMS Content:**")
                    st.code(notification['sms_content'])
            
            elif notification.get('notification_type') == 'push':
                if notification.get('push_title'):
                    st.write(f"**Push Title:** {notification['push_title']}")
                if notification.get('push_body'):
                    st.write(f"**Push Body:** {notification['push_body']}")
                if notification.get('push_data'):
                    st.write("**Push Data:**")
                    st.json(notification['push_data'])
            
            # Delivery timeline
            st.subheader("Delivery Timeline")
            
            # Sample timeline
            timeline = [
                {"timestamp": "2024-01-15 10:30:00", "event": "Notification Created", "description": "Notification was created successfully"},
                {"timestamp": "2024-01-15 10:31:00", "event": "Notification Sent", "description": "Notification was sent to delivery service"},
                {"timestamp": "2024-01-15 10:32:00", "event": "Notification Delivered", "description": "Notification was delivered successfully"},
                {"timestamp": "2024-01-15 10:35:00", "event": "Notification Opened", "description": "Recipient opened the notification"}
            ]
            
            for event in timeline:
                st.write(f"**{event['timestamp']}** - {event['event']}: {event['description']}")
            
            # Notification actions
            st.subheader("Notification Actions")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if st.button("Resend Notification"):
                    st.info("Notification resending would be processed here")
            
            with col2:
                if st.button("View Tracking"):
                    st.info("Notification tracking would be displayed here")
            
            with col3:
                if st.button("View Logs"):
                    st.info("Notification logs would be displayed here")
            
            with col4:
                if st.button("Export Data"):
                    st.info("Notification data would be exported here")
        else:
            st.error(f"❌ Failed to get notification details: {result.get('error', 'Unknown error')}")

def show_analytics():
    """Analytics page"""
    st.header("📈 Notification Analytics")
    
    # Analytics tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Delivery Analytics", "Engagement Analytics", "Channel Analytics", "Performance Metrics"])
    
    with tab1:
        st.subheader("Delivery Analytics")
        
        # Sample delivery data
        delivery_data = {
            "total_notifications": 15678,
            "delivery_rate": 95.0,
            "bounce_rate": 2.1,
            "complaint_rate": 0.3,
            "delivery_by_hour": [
                {"hour": "09:00", "delivered": 234, "failed": 12},
                {"hour": "10:00", "delivered": 456, "failed": 23},
                {"hour": "11:00", "delivered": 678, "failed": 34},
                {"hour": "12:00", "delivered": 789, "failed": 45},
                {"hour": "13:00", "delivered": 567, "failed": 23},
                {"hour": "14:00", "delivered": 345, "failed": 12},
                {"hour": "15:00", "delivered": 234, "failed": 8},
                {"hour": "16:00", "delivered": 123, "failed": 5}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Notifications", delivery_data["total_notifications"])
        
        with col2:
            st.metric("Delivery Rate", f"{delivery_data['delivery_rate']}%")
        
        with col3:
            st.metric("Bounce Rate", f"{delivery_data['bounce_rate']}%")
        
        with col4:
            st.metric("Complaint Rate", f"{delivery_data['complaint_rate']}%")
        
        # Delivery by hour chart
        import pandas as pd
        import plotly.express as px
        
        df = pd.DataFrame(delivery_data["delivery_by_hour"])
        fig = px.bar(df, x="hour", y="delivered", title="Notifications Delivered by Hour")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        st.subheader("Engagement Analytics")
        
        # Sample engagement data
        engagement_data = {
            "open_rate": 23.5,
            "click_rate": 4.2,
            "unsubscribe_rate": 0.8,
            "forward_rate": 1.2,
            "engagement_by_type": [
                {"type": "email", "open_rate": 25.3, "click_rate": 4.5},
                {"type": "sms", "open_rate": 98.5, "click_rate": 12.3},
                {"type": "push", "open_rate": 45.7, "click_rate": 8.9},
                {"type": "webhook", "open_rate": 100.0, "click_rate": 0.0}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Open Rate", f"{engagement_data['open_rate']}%")
        
        with col2:
            st.metric("Click Rate", f"{engagement_data['click_rate']}%")
        
        with col3:
            st.metric("Unsubscribe Rate", f"{engagement_data['unsubscribe_rate']}%")
        
        with col4:
            st.metric("Forward Rate", f"{engagement_data['forward_rate']}%")
        
        # Engagement by type chart
        df = pd.DataFrame(engagement_data["engagement_by_type"])
        fig = px.bar(df, x="type", y="open_rate", title="Open Rate by Notification Type")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.subheader("Channel Analytics")
        
        # Sample channel data
        channel_data = {
            "email_notifications": 12345,
            "sms_notifications": 2345,
            "push_notifications": 678,
            "webhook_notifications": 310,
            "channel_performance": [
                {"channel": "email", "volume": 12345, "success_rate": 94.2, "cost": 0.05},
                {"channel": "sms", "volume": 2345, "success_rate": 98.5, "cost": 0.10},
                {"channel": "push", "volume": 678, "success_rate": 89.3, "cost": 0.01},
                {"channel": "webhook", "volume": 310, "success_rate": 99.1, "cost": 0.02}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Email Notifications", channel_data["email_notifications"])
        
        with col2:
            st.metric("SMS Notifications", channel_data["sms_notifications"])
        
        with col3:
            st.metric("Push Notifications", channel_data["push_notifications"])
        
        with col4:
            st.metric("Webhook Notifications", channel_data["webhook_notifications"])
        
        # Channel performance chart
        df = pd.DataFrame(channel_data["channel_performance"])
        fig = px.bar(df, x="channel", y="success_rate", title="Success Rate by Channel")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab4:
        st.subheader("Performance Metrics")
        
        # Sample performance data
        performance_data = {
            "average_delivery_time": 2.5,
            "system_uptime": 99.9,
            "api_response_time": 120,
            "queue_processing_time": 0.8,
            "error_rate": 0.1,
            "retry_success_rate": 85.3,
            "automation_rate": 92.7,
            "compliance_rate": 98.9
        }
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Average Delivery Time", f"{performance_data['average_delivery_time']} seconds")
            st.metric("System Uptime", f"{performance_data['system_uptime']}%")
            st.metric("API Response Time", f"{performance_data['api_response_time']} ms")
            st.metric("Queue Processing Time", f"{performance_data['queue_processing_time']} seconds")
        
        with col2:
            st.metric("Error Rate", f"{performance_data['error_rate']}%")
            st.metric("Retry Success Rate", f"{performance_data['retry_success_rate']}%")
            st.metric("Automation Rate", f"{performance_data['automation_rate']}%")
            st.metric("Compliance Rate", f"{performance_data['compliance_rate']}%")

if __name__ == "__main__":
    main()




