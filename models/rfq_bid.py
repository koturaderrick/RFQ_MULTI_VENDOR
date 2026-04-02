from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RFQBid(models.Model):
    _name = 'rfq.bid'
    _description = 'RFQ Bid'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'bid_amount asc'  # Sort bids by amount in ascending order (cheapest first)

    # Fields for bid reference, RFQ, vendor, and bid details
    name = fields.Char(
        string='Bid Reference',
        required=True,
        copy=False,
        default=lambda self: _('New'),
    )
    rfq_id = fields.Many2one(
        'purchase.order',
        string='RFQ',
        required=True,
        ondelete='cascade',  # Delete bid if RFQ is deleted
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        required=True,
        domain=[('supplier_rank', '>', 0)],  # Only allow vendors with supplier rank > 0
    )
    bid_amount = fields.Float(string='Bid Amount', required=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,  # Default to company currency
    )
    delivery_days = fields.Integer(string='Delivery (Days)')
    validity_date = fields.Date(string='Valid Until')
    notes = fields.Text(string='Notes')

    # Bid state and tracking
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('won', 'Won'),
        ('lost', 'Lost'),
    ], string='Status', default='submitted', tracking=True)  # Default state is 'submitted'

    is_winner = fields.Boolean(string='Winner', default=False)  # Flag for winning bid
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Generated PO',
        readonly=True,
        copy=False,  # Do not copy this field
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Override create method to set bid reference to vendor name if not provided
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vendor = self.env['res.partner'].browse(vals.get('vendor_id'))
                vals['name'] = vendor.name or _('New')
        return super().create(vals_list)

    def action_set_draft(self):
        # Set bid state back to 'draft'
        for bid in self:
            bid.state = 'draft'

    def action_mark_winner(self):
        """Mark this bid as the winner, update other bids, and create a purchase order."""
        for bid in self:
            if bid.state != 'submitted':
                raise UserError(_('Only submitted bids can be marked as winner.'))

            # Mark this bid as 'won' and set it as the winner
            bid.state = 'won'
            bid.is_winner = True

            # Set all other bids for the same RFQ as 'lost'
            other_bids = bid.rfq_id.bid_ids.filtered(lambda b: b.id != bid.id)
            other_bids.write({'state': 'lost', 'is_winner': False})

            # Create purchase order lines based on RFQ lines
            po_lines = []
            for line in bid.rfq_id.order_line:
                po_lines.append((0, 0, {
                    'product_id': line.product_id.id,
                    'name': line.name or line.product_id.name,
                    'product_qty': line.product_qty,
                    'price_unit': bid.bid_amount,  # Use bid amount as price
                    'date_planned': fields.Datetime.now(),
                    'product_uom_id': line.product_uom_id.id,
                }))

            # Create a new purchase order for the winning bid
            po = self.env['purchase.order'].create({
                'partner_id': bid.vendor_id.id,
                'origin': bid.rfq_id.name,  # Link to the original RFQ
                'order_line': po_lines,
            })

            # Link the purchase order and winning bid for traceability
            bid.purchase_order_id = po.id
            bid.rfq_id.winning_bid_id = bid.id
