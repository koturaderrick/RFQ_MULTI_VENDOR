from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PurchaseRequest(models.Model):
    _name = 'purchase.request'
    _description = 'Purchase Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_request desc'  # Orders requests by request date in descending order

    name = fields.Char(
        string='Request Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),  # Default name is 'New' until a sequence is assigned
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted to Procurement'),
        ('approved', 'Approved'),
        ('rfq_created', 'RFQ Created'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', tracking=True)  # Tracks the state of the request

    requested_by = fields.Many2one(
        'res.users',
        string='Requested By',
        default=lambda self: self.env.user,  # Defaults to the current user
        required=True,
    )
    date_request = fields.Date(
        string='Request Date',
        default=fields.Date.context_today,  # Defaults to today's date
        required=True,
    )
    date_required = fields.Date(string='Required By', required=True)  # Deadline for the request
    description = fields.Text(string='Justification', required=True)  # Reason for the request

    vendor_ids = fields.Many2many(
        'res.partner',
        'purchase_request_vendor_rel',
        'request_id',
        'partner_id',
        string='Vendors to Invite',
        domain=[('supplier_rank', '>', 0)],  # Only suppliers are selectable
        help='Select one or more vendors to send RFQs to when this request is approved.',
    )

    line_ids = fields.One2many(
        'purchase.request.line',
        'request_id',
        string='Requested Items',  # Items requested in this purchase request
    )
    rfq_ids = fields.One2many(
        'purchase.order',
        'purchase_request_id',
        string='RFQs',  # RFQs generated from this purchase request
    )
    rfq_count = fields.Integer(compute='_compute_rfq_count', string='RFQs')  # Count of RFQs

    @api.model_create_multi
    def create(self, vals_list):
        # Assigns a sequence to the request name if it's 'New'
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('purchase.request') or _('New')
        return super().create(vals_list)

    @api.depends('rfq_ids')
    def _compute_rfq_count(self):
        # Computes the number of RFQs linked to this request
        for rec in self:
            rec.rfq_count = len(rec.rfq_ids)

    def action_submit(self):
        # Submits the request for procurement approval
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Add at least one item before submitting.'))
            rec.state = 'submitted'

    def action_approve(self):
        # Approves the purchase request
        for rec in self:
            rec.state = 'approved'

    def action_reject(self):
        # Rejects the purchase request
        for rec in self:
            rec.state = 'rejected'

    def action_reset_draft(self):
        # Resets the request to draft state
        for rec in self:
            rec.state = 'draft'

    def action_create_rfq(self):
        """
        Creates one RFQ per vendor selected, including all items from the request.
        """
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Only approved requests can be converted to RFQs.'))
        if not self.vendor_ids:
            raise UserError(_('Please add at least one vendor before creating RFQs.'))

        for vendor in self.vendor_ids:
            # Prepare RFQ lines based on the requested items
            lines = [(0, 0, {
                'product_id': l.product_id.id,
                'name': l.description or l.product_id.name,
                'product_qty': l.qty,
                'product_uom_id': l.uom_id.id,
                'price_unit': l.estimated_price,
                'date_planned': self.date_required,
            }) for l in self.line_ids]

            # Create an RFQ for the vendor
            rfq = self.env['purchase.order'].create({
        # Assign first vendor as main vendor (Odoo requires this)
        'partner_id': self.vendor_ids[0].id,

        # Assign ALL vendors using Many2many
        'vendor_ids': [(6, 0, self.vendor_ids.ids)],

        'purchase_request_id': self.id,
        'origin': self.name,
        'order_line': lines,
    })


        self.state = 'rfq_created'  # Update state to RFQ created
        return self.action_view_rfqs()

    def action_view_rfqs(self):
        # Opens a view showing all RFQs linked to this request
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('RFQs'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('purchase_request_id', '=', self.id)],
        }


class PurchaseRequestLine(models.Model):
    _name = 'purchase.request.line'
    _description = 'Purchase Request Line'

    request_id = fields.Many2one('purchase.request', required=True, ondelete='cascade')  # Links to the parent request
    product_id = fields.Many2one('product.product', string='Product', required=True)  # Product being requested
    description = fields.Char(string='Description')  # Description of the product
    qty = fields.Float(string='Quantity', default=1.0, required=True)  # Quantity requested
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True)  # Unit of measure for the product
    estimated_price = fields.Float(string='Estimated Unit Price')  # Estimated price per unit

    @api.onchange('product_id')
    def _onchange_product_id(self):
        # Automatically fills fields when a product is selected
        if self.product_id:
            self.description = self.product_id.name
            # Use the purchase UoM if available, otherwise default to the product's UoM
            tmpl = self.product_id.product_tmpl_id
            self.uom_id = getattr(tmpl, 'uom_po_id', False) or self.product_id.uom_id
            self.estimated_price = self.product_id.standard_price
