# PharmaSight Frontend

Modern, responsive web frontend for PharmaSight Pharmacy Management System.

## Features

- ✅ Clean, modern UI with sidebar navigation
- ✅ Items management (CRUD with breaking bulk)
- ✅ Point of Sale (POS) with automatic pricing
- ✅ Purchases/GRN management
- ✅ Inventory/Stock viewing
- ✅ Settings configuration
- ✅ Responsive design (mobile-friendly)
- ✅ Toast notifications
- ✅ Modal dialogs

## Structure

```
frontend/
├── index.html          # Main HTML file
├── css/
│   └── style.css       # Main stylesheet
├── js/
│   ├── config.js       # Configuration
│   ├── api.js          # API client
│   ├── utils.js        # Utility functions
│   ├── app.js          # Main app logic
│   └── pages/
│       ├── dashboard.js
│       ├── items.js
│       ├── sales.js
│       ├── purchases.js
│       ├── inventory.js
│       └── settings.js
└── README.md
```

## Getting Started

1. **Open in Browser**
   - Simply open `index.html` in a modern browser
   - Or use a local server:
     ```bash
     # Python
     python -m http.server 3000
     
     # Node.js
     npx serve
     ```

2. **Configure Settings**
   - Click on Settings in the sidebar
   - Enter your API base URL (default: http://localhost:8000)
   - Enter Company ID and Branch ID (UUIDs from database)
   - Enter User ID (for audit trail)
   - Save settings

3. **Start Using**
   - Make sure FastAPI backend is running
   - Navigate to different sections using the sidebar
   - Start by adding items, then create GRNs, then process sales

## Pages

### Dashboard
- Overview statistics
- Total items, stock value, sales, expiring items

### Items
- List all items
- Add new items with breaking bulk configuration
- Edit items
- View unit conversions

### Sales (POS)
- Search and add items to cart
- Automatic pricing with margin display
- Unit-aware quantity selection
- Real-time cart calculation
- Process sales with FEFO allocation

### Purchases
- Create GRN (Goods Received Notes)
- Add items with batch and expiry
- Automatic stock updates

### Inventory
- View all stock
- Search items
- View detailed stock by batch (FEFO order)
- Unit breakdown display

### Settings
- Configure API connection
- Set Company/Branch/User IDs
- Configure VAT rate

## API Integration

The frontend uses the FastAPI backend endpoints:
- Items: `/api/items`
- Inventory: `/api/inventory`
- Sales: `/api/sales`
- Purchases: `/api/purchases`

All API calls are handled through the `API` object in `js/api.js`.

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers

## Development

The frontend is vanilla JavaScript (no frameworks) for simplicity and performance. All code is organized in modules for maintainability.

### Adding New Features

1. Create page function in `js/pages/`
2. Add navigation item in `index.html`
3. Add page div in `index.html`
4. Register in `app.js` switch statement

## Notes

- Settings are stored in localStorage
- No authentication yet (to be implemented)
- All API calls require Company ID and Branch ID to be set
- User ID is required for creating transactions (audit trail)

