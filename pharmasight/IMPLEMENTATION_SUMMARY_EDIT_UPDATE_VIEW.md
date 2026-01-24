# Edit/Update/View Implementation Summary

## Overview
This document summarizes the unified edit/update/view logic implemented across all document types in PharmaSight.

## Document Types and Status Rules

### 1. **Purchase Orders**
- **Editable Status**: `PENDING` only
- **Non-Editable Statuses**: `APPROVED`, `RECEIVED`, `CANCELLED`
- **Features**:
  - ✅ Edit mode with full item population
  - ✅ Update endpoint (PUT) - only for PENDING
  - ✅ Delete endpoint (DELETE) - only for PENDING
  - ✅ Auto-save on item changes (2 second debounce)
  - ✅ Status-based button disabling
  - ✅ Proper error handling

### 2. **Supplier Invoices**
- **Editable Status**: `DRAFT` only
- **Non-Editable Statuses**: `BATCHED` (stock already added)
- **Features**:
  - ✅ Edit mode with full item population
  - ✅ Update endpoint (PUT) - only for DRAFT
  - ✅ Delete endpoint (DELETE) - only for DRAFT
  - ✅ Batch endpoint (POST) - converts DRAFT to BATCHED
  - ✅ Auto-save on item changes (2 second debounce)
  - ✅ Status-based button disabling
  - ✅ Payment tracking (amount paid, balance)

### 3. **Sales Invoices**
- **Editable Status**: NONE (KRA Compliant)
- **Status**: Always `FINALIZED` after creation
- **Features**:
  - ✅ View-only mode (read-only)
  - ✅ No edit/update/delete endpoints (KRA compliance)
  - ✅ Print functionality
  - ✅ Full item details display

### 4. **Quotations**
- **Editable Status**: `draft` only
- **Non-Editable Statuses**: `sent`, `accepted`, `rejected`, `converted`
- **Features**:
  - ✅ Edit mode with full item population
  - ✅ Update endpoint (PUT) - only for draft
  - ✅ Delete endpoint (DELETE) - only for draft
  - ✅ Convert to invoice functionality
  - ⚠️ Auto-save: To be implemented
  - ⚠️ Status-based button disabling: To be implemented

### 5. **Credit Notes**
- **Status**: To be determined
- **Features**: To be implemented

## Common Patterns

### Backend Endpoints Pattern

All editable documents follow this pattern:

```python
@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: UUID, db: Session = Depends(get_db)):
    """Get document by ID with full item details"""
    # Load with items and item relationships
    document = db.query(Document).options(
        selectinload(Document.items).selectinload(DocumentItem.item)
    ).filter(Document.id == document_id).first()
    
    # Enhance items with full item details
    for item in document.items:
        if item.item:
            item.item_code = item.item.sku or ''
            item.item_name = item.item.name or ''
            # ... other fields
    
    return document

@router.put("/{document_id}", response_model=DocumentResponse)
def update_document(document_id: UUID, update: DocumentCreate, db: Session = Depends(get_db)):
    """Update document (only if status allows)"""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if document.status != "EDITABLE_STATUS":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update document with status {document.status}."
        )
    # ... update logic

@router.delete("/{document_id}", status_code=status.HTTP_200_OK)
def delete_document(document_id: UUID, db: Session = Depends(get_db)):
    """Delete document (only if status allows)"""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if document.status != "EDITABLE_STATUS":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete document with status {document.status}."
        )
    # ... delete logic
    return {"message": "Document deleted successfully", "deleted": True}
```

### Frontend Pattern

All editable documents follow this pattern:

```javascript
// 1. View/Edit function
async function viewDocument(documentId) {
    const document = await API.getDocument(documentId);
    
    if (document.status !== 'EDITABLE_STATUS') {
        // Show read-only view
        return;
    }
    
    // Set edit mode
    currentDocument = {
        id: documentId,
        mode: 'edit',
        documentData: document,
        status: document.status
    };
    
    // Load edit page
    await renderCreateDocumentPage();
}

// 2. Delete function with status check
async function deleteDocument(documentId) {
    // Check status first
    const document = await API.getDocument(documentId);
    if (document.status !== 'EDITABLE_STATUS') {
        showToast(`Cannot delete document with status ${document.status}`, 'error');
        return;
    }
    
    // Confirm and delete
    if (!confirm('Are you sure?')) return;
    
    await API.deleteDocument(documentId);
    // ... handle success
}

// 3. Auto-save function
async function autoSaveDocument() {
    if (!currentDocument || currentDocument.status !== 'EDITABLE_STATUS') {
        return;
    }
    
    // Debounce and save
    clearTimeout(window.autoSaveTimeout);
    window.autoSaveTimeout = setTimeout(async () => {
        const formData = getFormData();
        const items = getItems();
        await API.updateDocument(currentDocument.id, { ...formData, items });
    }, 2000);
}

// 4. onItemsChange callback
onItemsChange: (validItems) => {
    // Update documentItems
    documentItems = validItems.map(...);
    
    // Trigger auto-save if editable
    if (currentDocument && currentDocument.status === 'EDITABLE_STATUS') {
        clearTimeout(window.autoSaveTimeout);
        window.autoSaveTimeout = setTimeout(() => {
            autoSaveDocument();
        }, 2000);
    }
}
```

## Implementation Status

| Document Type | GET (View) | PUT (Update) | DELETE | Auto-Save | Status Restrictions | Notes |
|--------------|------------|--------------|--------|-----------|---------------------|-------|
| Purchase Orders | ✅ | ✅ | ✅ | ✅ | ✅ | PENDING only |
| Supplier Invoices | ✅ | ✅ | ✅ | ✅ | ✅ | DRAFT only |
| Sales Invoices | ✅ | ❌ | ❌ | ❌ | ✅ | KRA compliant - view only |
| Quotations | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | draft only - needs frontend updates |
| Credit Notes | ❌ | ❌ | ❌ | ❌ | ❌ | To be implemented |

## Next Steps

1. **Quotations Frontend**: Add status-based restrictions and auto-save
2. **Credit Notes**: Implement full CRUD with status restrictions
3. **Unified Helper Functions**: Create shared functions for common operations
4. **Testing**: Test all document types for consistency

## Files Modified

### Backend
- `pharmasight/backend/app/api/purchases.py` - Purchase Orders & Supplier Invoices
- `pharmasight/backend/app/api/sales.py` - Sales Invoices (view-only)
- `pharmasight/backend/app/api/quotations.py` - Quotations

### Frontend
- `pharmasight/frontend/js/pages/purchases.js` - Purchase Orders & Supplier Invoices
- `pharmasight/frontend/js/pages/sales.js` - Sales Invoices & Quotations
