"""
Analyze Excel template columns - which are used vs unused
"""
import pandas as pd
import sys

excel_path = r'C:\Users\Envy\Downloads\pharmasight_template_fixed_20260126_143121.xlsx'

try:
    df = pd.read_excel(excel_path)
    
    # Columns we use in 3-tier system
    used_columns = [
        'Item name*',
        'Item code',
        'Description',
        'Category',
        'Supplier_Unit',
        'Wholesale_Unit',
        'Retail_Unit',
        'Pack_Size',
        'Can_Break_Bulk',
        'Base Unit (x)',
        'Secondary Unit (y)',
        'Conversion Rate (n) (x = ny)',
        'Purchase_Price_per_Supplier_Unit',
        'Wholesale_Price_per_Wholesale_Unit',
        'Retail_Price_per_Retail_Unit',
        'Sale price',
        'VAT_Category',
        'VAT_Rate',
        'Supplier',
        'Current stock quantity',
        # Fallback columns
        'Price_List_Last_Cost',
        'Price_List_Retail_Price',
        'Price_List_Wholesale_Price',
        'Price_List_Retail_Unit_Price',
        'Price_List_Wholesale_Unit_Price',
        'Purchase price',
    ]
    
    print("=" * 70)
    print("EXCEL TEMPLATE COLUMN ANALYSIS")
    print("=" * 70)
    print(f"\nTotal Rows: {len(df):,}")
    print(f"Total Columns: {len(df.columns)}\n")
    
    # Find which columns are used
    actual_used = [c for c in used_columns if c in df.columns]
    unused = [c for c in df.columns if c not in used_columns]
    
    print("=" * 70)
    print(f"[USED] COLUMNS ({len(actual_used)})")
    print("=" * 70)
    for i, col in enumerate(actual_used, 1):
        print(f"  {i:2d}. {col}")
    
    print(f"\n{'=' * 70}")
    print(f"[UNUSED] COLUMNS ({len(unused)})")
    print("=" * 70)
    for i, col in enumerate(unused, 1):
        print(f"  {i:2d}. {col}")
    
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print("=" * 70)
    print(f"Used: {len(actual_used)} columns")
    print(f"Unused: {len(unused)} columns")
    print(f"Total: {len(df.columns)} columns")
    print(f"\nUsage: {len(actual_used)/len(df.columns)*100:.1f}% of columns are used")
    
    # Check for missing critical columns
    critical = ['Item name*', 'Supplier_Unit', 'Wholesale_Unit', 'Retail_Unit', 
                'Pack_Size', 'Purchase_Price_per_Supplier_Unit', 
                'Wholesale_Price_per_Wholesale_Unit', 'Retail_Price_per_Retail_Unit']
    missing = [c for c in critical if c not in df.columns]
    if missing:
        print(f"\n[WARNING] Missing critical columns: {', '.join(missing)}")
    else:
        print("\n[OK] All critical 3-tier columns are present!")
        
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
