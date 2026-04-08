from odoo import models, fields, api, _
from odoo.exceptions import UserError

# This is the main model for Purchase Requests
class PurchaseRequest(models.Model):
    _name = 'purchase.request'
    _description = 'Purchase Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_request desc'  # Sort by request date in descending order

    # Field for the unique reference of the request
    name = fields.Char(
        string='Request Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )

    # Status of the request
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted to Procurement'),
        ('approved', 'Approved'),
        ('rfq_created', 'RFQ Created'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', tracking=True)

    # Who created the request
    requested_by = fields.Many2one(
        'res.users',
        string='Requested By',
        default=lambda self: self.env.user,
        required=True,
    )

    # Date when the request was made
    date_request = fields.Date(
        string='Request Date',
        default=fields.Date.context_today,
        required=True,
    )

    # When the items are needed
    date_required = fields.Date(string='Required By', required=True)
    description = fields.Text(string='Justification', required=True)  # Why this request is needed

    # Vendors to send RFQs to
    vendor_ids = fields.Many2many(
        'res.partner',
        'purchase_request_vendor_rel',
        'request_id',
        'partner_id',
        string='Vendors to Invite',
        domain=[('supplier_rank', '>', 0)],
        help='Vendors to send RFQs to once this request is approved.',
    )

    # Items being requested
    line_ids = fields.One2many(
        'purchase.request.line',
        'request_id',
        string='Requested Items',
    )

    # RFQs created from this request
    rfq_ids = fields.One2many(
        'purchase.order',
        'purchase_request_id',
        string='RFQs',
    )

    # Count of RFQs for this request
    rfq_count = fields.Integer(compute='_compute_rfq_count', string='RFQs')

    # Override create method to set a unique name
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('purchase.request') or _('New')
                )
        return super().create(vals_list)

    # Compute the number of RFQs linked to this request
    @api.depends('rfq_ids')
    def _compute_rfq_count(self):
        for rec in self:
            rec.rfq_count = len(rec.rfq_ids)

    # Submit the request for approval
    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Add at least one item before submitting.'))
            rec.state = 'submitted'

    # Approve the request
    def action_approve(self):
        for rec in self:
            rec.state = 'approved'

    # Reject the request
    def action_reject(self):
        for rec in self:
            rec.state = 'rejected'

    # Reset the request back to draft
    def action_reset_draft(self):
        for rec in self:
            rec.state = 'draft'

    # Create an RFQ for the first vendor in the list
    def action_create_rfq(self):
        """Creates ONLY ONE RFQ for the first vendor selected."""
        self.ensure_one()

        if self.state != 'approved':
            raise UserError(_('Only approved requests can be converted to RFQs.'))

        if not self.vendor_ids:
            raise UserError(_('Please add at least one vendor before creating RFQs.'))

        # FIX: We grab only the FIRST vendor from the list instead of looping
        vendor = self.vendor_ids[0]

        # Prepare the lines for the single RFQ
        lines = [(0, 0, {
            'product_id': l.product_id.id,
            'name': l.description or l.product_id.name,
            'product_qty': l.qty,
            'product_uom_id': l.uom_id.id,
            'price_unit': l.estimated_price,
            'date_planned': self.date_required,
        }) for l in self.line_ids]

        # Create only ONE purchase order
        self.env['purchase.order'].create({
            'partner_id': vendor.id,
            'purchase_request_id': self.id,
            'origin': self.name,
            'order_line': lines,
        })

        self.state = 'rfq_created'
        return self.action_view_rfqs()

    # View the RFQs linked to this request
    def action_view_rfqs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('RFQs'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('purchase_request_id', '=', self.id)],
        }


# Model for the items in the purchase request
class PurchaseRequestLine(models.Model):
    _name = 'purchase.request.line'
    _description = 'Purchase Request Line'

    request_id = fields.Many2one('purchase.request', required=True, ondelete='cascade')  # Link to the main request
    product_id = fields.Many2one('product.product', string='Product', required=True)  # The product being requested
    description = fields.Char(string='Description')  # Description of the product
    qty = fields.Float(string='Quantity', default=1.0, required=True)  # How many units
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True)  # Unit of measure
    estimated_price = fields.Float(string='Estimated Unit Price')  # Estimated price per unit

    # Automatically fill in some fields when a product is selected
    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.description = self.product_id.name
            tmpl = self.product_id.product_tmpl_id
            self.uom_id = getattr(tmpl, 'uom_po_id', False) or self.product_id.uom_id
            self.estimated_price = self.product_id.standard_price