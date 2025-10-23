#!/usr/bin/env python3
"""
ZeroQue Catalog Service - Streamlit Demo
Product catalog management and search
"""

import streamlit as st
import requests
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List

# Page configuration
st.set_page_config(
    page_title="ZeroQue Catalog Service",
    page_icon="📦",
    layout="wide"
)

# Service configuration
SERVICE_PORT = 8215
BASE_URL = f"http://localhost:{SERVICE_PORT}"


# API Configuration
API_KEY = os.getenv('CATALOG_API_KEY', 'zq_demo_key_for_testing')

# Test data
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"

def make_request(endpoint: str, method: str = "GET", data: Dict = None) -> Dict[str, Any]:
    """Make API request with authentication"""
    try:
        url = f"{BASE_URL}{endpoint}"
        
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": API_KEY
        }
        
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            response = requests.post(url, json=data, headers=headers, timeout=10)
        else:
            return {"success": False, "error": f"Unsupported method: {method}"}
            
        if response.status_code >= 200 and response.status_code < 300:
            return {
                "success": True,
                "data": response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
                "status_code": response.status_code
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}",
                "status_code": response.status_code
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

def main():
    """Main application"""
    st.title("📦 ZeroQue Catalog Service")
    st.markdown("Product catalog management and search")
    
    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.selectbox(
        "Select Page",
        ["Dashboard", "Products", "Categories", "Search", "Analytics"]
    )
    
    # Initialize session state
    if "tenant_id" not in st.session_state:
        st.session_state.tenant_id = TEST_TENANT_ID
    
    # Route to selected page
    if page == "Dashboard":
        show_dashboard()
    elif page == "Products":
        show_products()
    elif page == "Categories":
        show_categories()
    elif page == "Search":
        show_search()
    elif page == "Analytics":
        show_analytics()

def show_dashboard():
    """Dashboard page"""
    st.header("📊 Catalog Dashboard")
    
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
        st.metric("Total Products", "1,234", "12")
    
    with col2:
        st.metric("Active Categories", "45", "3")
    
    with col3:
        st.metric("Search Queries", "5,678", "234")
    
    with col4:
        st.metric("API Calls", "12,345", "567")
    
    # Recent activity
    st.subheader("Recent Activity")
    
    # Sample activity data
    activity_data = [
        {"timestamp": "2024-01-15 10:30:00", "action": "Product Created", "details": "New product 'Demo Product 1'"},
        {"timestamp": "2024-01-15 10:25:00", "action": "Category Updated", "details": "Category 'Electronics' modified"},
        {"timestamp": "2024-01-15 10:20:00", "action": "Search Query", "details": "Search for 'laptop' returned 25 results"},
        {"timestamp": "2024-01-15 10:15:00", "action": "Product Updated", "details": "Product 'Demo Product 2' price updated"},
        {"timestamp": "2024-01-15 10:10:00", "action": "Category Created", "details": "New category 'Accessories' created"}
    ]
    
    for activity in activity_data:
        st.write(f"**{activity['timestamp']}** - {activity['action']}: {activity['details']}")

def show_products():
    """Products page"""
    st.header("📦 Product Management")
    
    # Create new product
    st.subheader("Create New Product")
    
    with st.form("create_product"):
        col1, col2 = st.columns(2)
        
        with col1:
            product_name = st.text_input("Product Name", value=f"Demo Product {uuid.uuid4().hex[:8]}")
            sku = st.text_input("SKU", value=f"SKU-{uuid.uuid4().hex[:8]}")
            category_id = st.text_input("Category ID", value="cat_123")
        
        with col2:
            base_price = st.number_input("Base Price", min_value=0.01, value=99.99, step=0.01)
            currency = st.selectbox("Currency", ["GBP", "USD", "EUR"])
            is_active = st.checkbox("Active", value=True)
        
        description = st.text_area("Description", value="This is a demo product for testing purposes.")
        
        if st.form_submit_button("Create Product"):
            product_data = {
                "tenant_id": st.session_state.tenant_id,
                "product_name": product_name,
                "sku": sku,
                "category_id": category_id,
                "base_price_minor": int(base_price * 100),
                "currency": currency,
                "description": description,
                "is_active": is_active
            }
            
            result = make_request("/products", "POST", product_data)
            
            if result["success"]:
                st.success("✅ Product created successfully!")
                st.json(result["data"])
            else:
                st.error(f"❌ Failed to create product: {result.get('error', 'Unknown error')}")
    
    # List products
    st.subheader("Product List")
    
    if st.button("Get Products"):
        result = make_request("/products", "GET")
        
        if result["success"]:
            products = result["data"]
            if products:
                st.success(f"✅ Found {len(products)} products")
                
                # Display products in a table
                for product in products:
                    with st.expander(f"Product: {product.get('product_name', 'Unknown')}"):
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.write(f"**SKU:** {product.get('sku', 'N/A')}")
                            st.write(f"**Category ID:** {product.get('category_id', 'N/A')}")
                            st.write(f"**Price:** {product.get('base_price_minor', 0) / 100:.2f} {product.get('currency', 'GBP')}")
                        
                        with col2:
                            st.write(f"**Active:** {product.get('is_active', False)}")
                            st.write(f"**Created:** {product.get('created_at', 'N/A')}")
                            st.write(f"**Updated:** {product.get('updated_at', 'N/A')}")
                        
                        st.write(f"**Description:** {product.get('description', 'No description')}")
            else:
                st.info("No products found")
        else:
            st.error(f"❌ Failed to get products: {result.get('error', 'Unknown error')}")

def show_categories():
    """Categories page"""
    st.header("📂 Category Management")
    
    # Create new category
    st.subheader("Create New Category")
    
    with st.form("create_category"):
        category_name = st.text_input("Category Name", value=f"Demo Category {uuid.uuid4().hex[:8]}")
        category_code = st.text_input("Category Code", value=f"CAT-{uuid.uuid4().hex[:8]}")
        description = st.text_area("Description", value="This is a demo category for testing purposes.")
        is_active = st.checkbox("Active", value=True)
        
        if st.form_submit_button("Create Category"):
            category_data = {
                "tenant_id": st.session_state.tenant_id,
                "category_name": category_name,
                "category_code": category_code,
                "description": description,
                "is_active": is_active
            }
            
            result = make_request("/categories", "POST", category_data)
            
            if result["success"]:
                st.success("✅ Category created successfully!")
                st.json(result["data"])
            else:
                st.error(f"❌ Failed to create category: {result.get('error', 'Unknown error')}")
    
    # List categories
    st.subheader("Category List")
    
    if st.button("Get Categories"):
        result = make_request("/categories", "GET")
        
        if result["success"]:
            categories = result["data"]
            if categories:
                st.success(f"✅ Found {len(categories)} categories")
                
                # Display categories in a table
                for category in categories:
                    with st.expander(f"Category: {category.get('category_name', 'Unknown')}"):
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.write(f"**Code:** {category.get('category_code', 'N/A')}")
                            st.write(f"**Active:** {category.get('is_active', False)}")
                        
                        with col2:
                            st.write(f"**Created:** {category.get('created_at', 'N/A')}")
                            st.write(f"**Updated:** {category.get('updated_at', 'N/A')}")
                        
                        st.write(f"**Description:** {category.get('description', 'No description')}")
            else:
                st.info("No categories found")
        else:
            st.error(f"❌ Failed to get categories: {result.get('error', 'Unknown error')}")

def show_search():
    """Search page"""
    st.header("🔍 Product Search")
    
    # Search form
    with st.form("search_products"):
        query = st.text_input("Search Query", placeholder="Enter product name, SKU, or description")
        
        col1, col2 = st.columns(2)
        
        with col1:
            category_id = st.text_input("Category ID (optional)", placeholder="Filter by category")
            min_price = st.number_input("Min Price", min_value=0.0, value=0.0, step=0.01)
        
        with col2:
            vendor_id = st.text_input("Vendor ID (optional)", placeholder="Filter by vendor")
            max_price = st.number_input("Max Price", min_value=0.0, value=1000.0, step=0.01)
        
        limit = st.slider("Results Limit", min_value=1, max_value=100, value=20)
        offset = st.slider("Offset", min_value=0, max_value=1000, value=0)
        
        if st.form_submit_button("Search Products"):
            search_data = {
                "query": query,
                "category_id": category_id if category_id else None,
                "vendor_id": vendor_id if vendor_id else None,
                "min_price": int(min_price * 100) if min_price > 0 else None,
                "max_price": int(max_price * 100) if max_price > 0 else None,
                "limit": limit,
                "offset": offset
            }
            
            result = make_request("/search", "POST", search_data)
            
            if result["success"]:
                products = result["data"]
                if products:
                    st.success(f"✅ Found {len(products)} products")
                    
                    # Display search results
                    for product in products:
                        with st.expander(f"Product: {product.get('product_name', 'Unknown')}"):
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                st.write(f"**SKU:** {product.get('sku', 'N/A')}")
                                st.write(f"**Category ID:** {product.get('category_id', 'N/A')}")
                                st.write(f"**Price:** {product.get('base_price_minor', 0) / 100:.2f} {product.get('currency', 'GBP')}")
                            
                            with col2:
                                st.write(f"**Active:** {product.get('is_active', False)}")
                                st.write(f"**Created:** {product.get('created_at', 'N/A')}")
                                st.write(f"**Updated:** {product.get('updated_at', 'N/A')}")
                            
                            st.write(f"**Description:** {product.get('description', 'No description')}")
                else:
                    st.info("No products found matching your search criteria")
            else:
                st.error(f"❌ Search failed: {result.get('error', 'Unknown error')}")
    
    # Search analytics
    st.subheader("Search Analytics")
    
    # Sample search analytics
    search_analytics = {
        "total_searches": 1234,
        "successful_searches": 1156,
        "failed_searches": 78,
        "average_results": 15.6,
        "top_queries": [
            {"query": "laptop", "count": 45},
            {"query": "phone", "count": 38},
            {"query": "tablet", "count": 32},
            {"query": "headphones", "count": 28},
            {"query": "camera", "count": 25}
        ]
    }
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Searches", search_analytics["total_searches"])
    
    with col2:
        st.metric("Success Rate", f"{(search_analytics['successful_searches'] / search_analytics['total_searches'] * 100):.1f}%")
    
    with col3:
        st.metric("Avg Results", search_analytics["average_results"])
    
    with col4:
        st.metric("Failed Searches", search_analytics["failed_searches"])
    
    # Top queries
    st.write("**Top Search Queries:**")
    for query_data in search_analytics["top_queries"]:
        st.write(f"- {query_data['query']}: {query_data['count']} searches")

def show_analytics():
    """Analytics page"""
    st.header("📈 Catalog Analytics")
    
    # Analytics tabs
    tab1, tab2, tab3 = st.tabs(["Product Analytics", "Category Analytics", "Search Analytics"])
    
    with tab1:
        st.subheader("Product Analytics")
        
        # Sample product analytics
        product_analytics = {
            "total_products": 1234,
            "active_products": 1156,
            "inactive_products": 78,
            "price_distribution": [
                {"range": "£0-£50", "count": 456},
                {"range": "£50-£100", "count": 345},
                {"range": "£100-£500", "count": 234},
                {"range": "£500+", "count": 199}
            ]
        }
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Products", product_analytics["total_products"])
        
        with col2:
            st.metric("Active Products", product_analytics["active_products"])
        
        with col3:
            st.metric("Inactive Products", product_analytics["inactive_products"])
        
        # Price distribution chart
        import pandas as pd
        import plotly.express as px
        
        df = pd.DataFrame(product_analytics["price_distribution"])
        fig = px.bar(df, x="range", y="count", title="Product Price Distribution")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        st.subheader("Category Analytics")
        
        # Sample category analytics
        category_analytics = {
            "total_categories": 45,
            "active_categories": 42,
            "inactive_categories": 3,
            "top_categories": [
                {"name": "Electronics", "product_count": 456},
                {"name": "Clothing", "product_count": 345},
                {"name": "Home & Garden", "product_count": 234},
                {"name": "Sports", "product_count": 199},
                {"name": "Books", "product_count": 156}
            ]
        }
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Categories", category_analytics["total_categories"])
        
        with col2:
            st.metric("Active Categories", category_analytics["active_categories"])
        
        with col3:
            st.metric("Inactive Categories", category_analytics["inactive_categories"])
        
        # Top categories chart
        df = pd.DataFrame(category_analytics["top_categories"])
        fig = px.pie(df, values="product_count", names="name", title="Top Categories by Product Count")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.subheader("Search Analytics")
        
        # Sample search analytics
        search_analytics = {
            "total_searches": 5678,
            "successful_searches": 5234,
            "failed_searches": 444,
            "average_results": 15.6,
            "search_trends": [
                {"date": "2024-01-01", "searches": 123},
                {"date": "2024-01-02", "searches": 145},
                {"date": "2024-01-03", "searches": 167},
                {"date": "2024-01-04", "searches": 189},
                {"date": "2024-01-05", "searches": 201}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Searches", search_analytics["total_searches"])
        
        with col2:
            st.metric("Success Rate", f"{(search_analytics['successful_searches'] / search_analytics['total_searches'] * 100):.1f}%")
        
        with col3:
            st.metric("Avg Results", search_analytics["average_results"])
        
        with col4:
            st.metric("Failed Searches", search_analytics["failed_searches"])
        
        # Search trends chart
        df = pd.DataFrame(search_analytics["search_trends"])
        fig = px.line(df, x="date", y="searches", title="Search Trends")
        st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()




