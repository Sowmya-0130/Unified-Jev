## SQL 
import urllib
from sqlalchemy import create_engine, inspect
from azure.search.documents import SearchClient
from API_unified import *


# Set the schema name dynamically
# category_name = 'retail'  # Modify this variable as needed
index_name = "dbo"
search_client = SearchClient(endpoint=AZURE_SEARCH_SERVICE_ENDPOINT,index_name=index_name,
                            credential=azure_search_credential
                            )
                            
# Parameters
server = 'sqlinternserver.database.windows.net'
database = 'sqlintern_database'
username = 'sqlserverintern'
password = 'intern@12345'
driver = 'ODBC Driver 18 for SQL Server'
encoding = 'ISO-8859-1'
# Set the schema name dynamically
# category_name = 'retail'  # Modify this variable as needed
category_name = 'dbo'
#hr
# Step 1: Connection string for Azure SQL Database
connection_string = f'mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}")}'

# Create the SQLAlchemy engine
engine = create_engine(connection_string)

# Step 2: Fetch tables from the specified schema dynamically
def get_schema_tables(engine, schema_name):
    inspector = inspect(engine)
    tables = inspector.get_table_names(schema=schema_name)
    
    schema_details = ""
    for table_name in tables:
        columns = inspector.get_columns(table_name, schema=schema_name)
        schema = f'schema = "{schema_name}", table_name = "{schema_name}.{table_name}", {table_name}_table = Table(\n'
        for column in columns:
            col_name = column['name']
            col_type = column['type']
            primary_key = "primary_key=True" if column.get("primary_key", False) else ""
            nullable = "nullable=False" if not column["nullable"] else ""
            schema += f'    Column("{col_name}", {col_type}, {primary_key} {nullable}),\n'
        schema = schema.rstrip(',\n')  # Remove the last comma and newline
        schema += "\n)\n\n"
        schema_details += schema

    return schema_details

# Fetch tables from the dynamically specified schema
all_table_schemas = get_schema_tables(engine, category_name)
# print(all_table_schemas)

# # **************************************************************************************************************************************************************************************
# # **************************************************************************************************************************************************************************************

# # ## SAP

# SAP_Data = """ Tables in schema 'DBADMIN':
#    - Cust_Dustributor_ID
#       Columns:
# ('DBADMIN', 'Cust_Dustributor_ID', 'Customer_ID', 1, 'NVARCHAR', 50, None, 'FALSE', None)
# ('DBADMIN', 'Cust_Dustributor_ID', 'Distributor_ID', 2, 'INTEGER', 10, 0, 'FALSE', None)
# --------------------------------------------------
#    - Distributor_Orders
#       Columns:
# ('DBADMIN', 'Distributor_Orders', 'Distributor_Order_ID', 1, 'INTEGER', 10, 0, 'FALSE', None)
# ('DBADMIN', 'Distributor_Orders', 'Distributor_ID', 2, 'INTEGER', 10, 0, 'TRUE', None)
# ('DBADMIN', 'Distributor_Orders', 'Order_Date', 3, 'DATE', 10, None, 'TRUE', None)
# ('DBADMIN', 'Distributor_Orders', 'Order_Status', 4, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Distributor_Orders', 'Total_Amount', 5, 'INTEGER', 10, 0, 'TRUE', None)
# ('DBADMIN', 'Distributor_Orders', 'Currency', 6, 'NVARCHAR', 50, None, 'TRUE', None)
# --------------------------------------------------
#    - Distributor_Products
#       Columns:
# ('DBADMIN', 'Distributor_Products', 'Distributor_Product_ID', 1, 'INTEGER', 10, 0, 'FALSE', None)
# ('DBADMIN', 'Distributor_Products', 'Distributor_ID', 2, 'INTEGER', 10, 0, 'TRUE', None)
# ('DBADMIN', 'Distributor_Products', 'Product_ID', 3, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Distributor_Products', 'Product_Name', 4, 'NVARCHAR', 100, None, 'TRUE', None)
# ('DBADMIN', 'Distributor_Products', 'Category', 5, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Distributor_Products', 'Price', 6, 'INTEGER', 10, 0, 'TRUE', None)
# ('DBADMIN', 'Distributor_Products', 'Currency', 7, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Distributor_Products', 'Available_Stock', 8, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Distributor_Products', 'Delivery_Lead_Time', 9, 'INTEGER', 10, 0, 'TRUE', None)
# --------------------------------------------------
#    - Distributors
#       Columns:
# ('DBADMIN', 'Distributors', 'Distributor_ID', 1, 'INTEGER', 10, 0, 'FALSE', None)
# ('DBADMIN', 'Distributors', 'Distributor_Name', 2, 'NVARCHAR', 100, None, 'TRUE', None)
# ('DBADMIN', 'Distributors', 'Contact_Person', 3, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Distributors', 'Email', 4, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Distributors', 'Phone', 5, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Distributors', 'Location', 6, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Distributors', 'Rating', 7, 'DECIMAL', 34, None, 'TRUE', None)
# ('DBADMIN', 'Distributors', 'Status', 8, 'NVARCHAR', 50, None, 'TRUE', None)
# --------------------------------------------------
#    - Product_Pricing_History
#       Columns:
# ('DBADMIN', 'Product_Pricing_History', 'Price_History_ID', 1, 'INTEGER', 10, 0, 'FALSE', None)
# ('DBADMIN', 'Product_Pricing_History', 'Distributor_ID', 2, 'INTEGER', 10, 0, 'TRUE', None)
# ('DBADMIN', 'Product_Pricing_History', 'Product_ID', 3, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Product_Pricing_History', 'Previous_Price', 4, 'INTEGER', 10, 0, 'TRUE', None)
# ('DBADMIN', 'Product_Pricing_History', 'New_Price', 5, 'INTEGER', 10, 0, 'TRUE', None)
# ('DBADMIN', 'Product_Pricing_History', 'Change_Date', 6, 'DATE', 10, None, 'TRUE', None)
# --------------------------------------------------
#    - Shipment_Tracking
#       Columns:
# ('DBADMIN', 'Shipment_Tracking', 'Shipment_ID', 1, 'INTEGER', 10, 0, 'FALSE', None)
# ('DBADMIN', 'Shipment_Tracking', 'Distributor_Order_ID', 2, 'INTEGER', 10, 0, 'TRUE', None)
# ('DBADMIN', 'Shipment_Tracking', 'Shipment_Date', 3, 'DATE', 10, None, 'TRUE', None)
# ('DBADMIN', 'Shipment_Tracking', 'Delivery_Status', 4, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Shipment_Tracking', 'Carrier', 5, 'NVARCHAR', 50, None, 'TRUE', None)
# ('DBADMIN', 'Shipment_Tracking', 'Estimated_Delivery_Date', 6, 'DATE', 10, None, 'TRUE', None)
# --------------------------------------------------


# """

# # Connect to SAP HANA
# try:
#     connection = dbapi.connect(
#         address=sap_address,
#         port=sap_port,
#         user=sap_user,
#         password=sap_password,
#         encrypt=True,   # Required for TLS/SSL connections
#         sslValidateCertificate=False  # Disable SSL validation (optional)
#     )
#     print("✅ Connected to SAP HANA successfully!")
# except Exception as e:
#     print(f"❌ Connection failed: {e}")


# # Function to get tables from SAP HANA
# def get_sap_tables():
#     cursor = connection.cursor()

#     # Fetch all tables from the DBADMIN schema
#     cursor.execute("SELECT TABLE_NAME FROM PUBLIC.TABLES WHERE SCHEMA_NAME = 'DBADMIN'")
#     tables = cursor.fetchall()  

#     schema_details = ""
#     for (table_name,) in tables:
#         # Fetch columns for each table
#         cursor.execute(f"SELECT COLUMN_NAME, DATA_TYPE_NAME FROM PUBLIC.TABLE_COLUMNS WHERE TABLE_NAME = '{table_name}' AND SCHEMA_NAME = 'DBADMIN'")
#         columns = cursor.fetchall()

#         # Format table schema
#         schema = f'schema = "DBADMIN", table_name = "DBADMIN.{table_name}", {table_name}_table = Table(\n'
#         for column_name, column_type in columns:
#             schema += f'    Column("{column_name}", {column_type}),\n'
#         schema = schema.rstrip(',\n') + "\n)\n\n"  # Remove last comma
#         schema_details += schema

#     return schema_details

# # Fetch and print SAP schema details
# Sap_Data = get_sap_tables()#
# # print(Sap_Data)

# **************************************************************************************************************************************************************************************
# **************************************************************************************************************************************************************************************


# ## Salesforce

# Salesforce_Data = """**Meta_Data for Salesforce DB**:

# Table Name: Customer_stockin__c     
# Field Name: Quantity_Left__c, Field Type: double     
# Field Name: Category__c, Field Type: string 
# Field Name: Product_Name__c, Field Type: string

# Table Name: Customer_Info__c
# Field Name: Customer_ID__c, Field Type: string 
# Field Name: Email_ID__c, Field Type: email
# """

# # Connect to Salesforce
# sf = Salesforce(username=salesforce_username, password=salesforce_password, security_token=salesforce_security_token, domain=salesforce_domain)

# print("✅ Connected to Salesforce successfully!")

# # Tables to fetch metadata for
# required_tables = ["Customer_stockin__c", "Customer_Info__c"]

# # Function to fetch metadata for required tables
# def get_selected_salesforce_metadata():
#     metadata_details = ""

#     for table in required_tables:
#         try:
#             metadata_details += f"Table Name: {table}\n"

#             # Fetch object fields
#             fields = sf.__getattr__(table).describe()["fields"]
#             for field in fields:
#                 field_name = field["name"]
#                 field_type = field["type"]
#                 metadata_details += f"  Field Name: {field_name}, Field Type: {field_type}\n"

#             metadata_details += "-" * 50 + "\n"  # Separator

#         except Exception as e:
#             print(f"⚠️ Error fetching metadata for {table}: {e}")

#     return metadata_details

# # Fetch and print metadata
# Salesforce_Data = get_selected_salesforce_metadata()
# print(Salesforce_Data)

# **************************************************************************************************************************************************************************************
# **************************************************************************************************************************************************************************************

## Eryl Data

Vector_Data = [ "policy","return","product features","discounts","discount rate", "dilvery terms", "restock", "damage", "warranty"] # vector db

Web_Search_Data =["stock market"]

# stock market--> selector type= vector search or web search
