{
    'name': 'RFQ Multi Vendor System',
    'version': '1.0',
    'summary': 'Multi-vendor RFQ, Bid Management, Winner Selection, Purchase Requests',
    'depends': ['purchase', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/purchase_request_views.xml',
        'views/purchase_order_views.xml',
        'views/rfq_bid_views.xml',
        'wizard/select_winner_views.xml',
    ],
    'installable': True,
    'application': False,
}
