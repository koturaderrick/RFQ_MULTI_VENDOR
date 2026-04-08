from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Field to assign multiple vendors to a single RFQ
    vendor_ids = fields.Many2many(
        'res.partner',
        'purchase_order_vendor_rel',
        'order_id',
        'partner_id',
        string='Assigned Vendors',
        domain=[('is_company', '=', True)],  # Only allow companies as vendors
    )

    # Field to track bids associated with the RFQ
    bid_ids = fields.One2many(
        'rfq.bid',
        'rfq_id',
        string='Bids',
    )

    # Computed field to count the number of bids
    bid_count = fields.Integer(
        compute='_compute_bid_count',
        string='Bid Count',
    )

    # Field to store the winning bid (if any)
    winning_bid_id = fields.Many2one(
        'rfq.bid',
        string='Winning Bid',
        readonly=True,
        copy=False,
    )

    # Field to link the RFQ to a purchase request
    purchase_request_id = fields.Many2one(
        'purchase.request',
        string='Purchase Request',
        readonly=True,
        copy=False,
    )

    @api.depends('bid_ids')
    def _compute_bid_count(self):
        """Compute the total number of bids for the RFQ."""
        for order in self:
            order.bid_count = len(order.bid_ids)

    @api.onchange('vendor_ids')
    def _onchange_vendor_ids(self):
        """
        Automatically set the first vendor as the primary partner
        when vendors are assigned to the RFQ.
        """
        if self.vendor_ids:
            self.partner_id = self.vendor_ids[0]
        else:
            self.partner_id = False

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override the create method to ensure the primary partner
        is set when vendors are assigned to the RFQ.
        """
        for vals in vals_list:
            if vals.get('vendor_ids') and not vals.get('partner_id'):
                for cmd in vals['vendor_ids']:
                    if cmd[0] == 6 and cmd[2]:  # Many2many replace command
                        vals['partner_id'] = cmd[2][0]
                        break
                    elif cmd[0] == 4:  # Many2many add command
                        vals['partner_id'] = cmd[1]
                        break
        return super().create(vals_list)

    def write(self, vals):
        """
        Override the write method to ensure the primary partner
        is updated when vendors are modified.
        """
        if vals.get('vendor_ids') and not vals.get('partner_id'):
            for cmd in vals['vendor_ids']:
                if cmd[0] == 6 and cmd[2]:  # Many2many replace command
                    vals['partner_id'] = cmd[2][0]
                    break
                elif cmd[0] == 4:  # Many2many add command
                    vals['partner_id'] = cmd[1]
                    break
        return super().write(vals)

    def action_view_bids(self):
        """
        Open a view to display all bids associated with the RFQ.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bids'),
            'res_model': 'rfq.bid',
            'view_mode': 'list,form',
            'domain': [('rfq_id', '=', self.id)],
            'context': {'default_rfq_id': self.id},
        }

    def action_rfq_send(self):
        """
        Send the RFQ to vendors. If no vendors are assigned,
        fallback to the default behavior.
        """
        self.ensure_one()
        if not self.vendor_ids:
            return super().action_rfq_send()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send RFQ to Vendors'),
            'res_model': 'rfq.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_rfq_id': self.id},
        }

    def action_open_select_winner(self):
        """
        Open a wizard to select the winning bid. Perform validations
        to ensure all bids have amounts and are in the 'Submitted' state.
        """
        self.ensure_one()

        if not self.bid_ids:
            raise UserError(_('No bids have been received for this RFQ yet.'))

        # Validation: Ensure all bids have a positive amount
        missing_amounts = self.bid_ids.filtered(lambda b: b.bid_amount <= 0.0)
        if missing_amounts:
            vendor_names = ", ".join(missing_amounts.mapped('vendor_id.name'))
            raise UserError(_(
                "Incomplete Data: You must enter a bid amount for all vendors before "
                "selecting a winner. Missing amounts for: %s"
            ) % vendor_names)

        # Validation: Ensure all bids are in the 'Submitted' state
        not_submitted = self.bid_ids.filtered(lambda b: b.state != 'submitted')
        if not_submitted:
            vendor_names = ", ".join(not_submitted.mapped('vendor_id.name'))
            raise UserError(_(
                "Action Required: All bids must be in 'Submitted' state. "
                "The following vendors are still in Draft or other states: %s"
            ) % vendor_names)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Select Winning Bid'),
            'res_model': 'rfq.select.winner.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_rfq_id': self.id},
        }