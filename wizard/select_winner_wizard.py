from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RFQSelectWinnerWizard(models.TransientModel):
    """Popup wizard for managers to compare bids and select a winner.

    On confirmation, it marks the winning bid as won, closes others,
    and creates a Purchase Order (PO) for the winning vendor.
    """

    _name = 'rfq.select.winner.wizard'
    _description = 'Select Winning Bid Wizard'

    # Reference to the RFQ (purchase order) this wizard is for
    rfq_id = fields.Many2one(
        'purchase.order',
        string='RFQ',
        required=True,
        readonly=True,
    )
    # Read-only table showing submitted bids for comparison
    bid_ids = fields.Many2many(
        'rfq.bid',
        string='Submitted Bids',
        compute='_compute_bid_ids',
    )
    # Field to select the winning bid, restricted to submitted bids for this RFQ
    winning_bid_id = fields.Many2one(
        'rfq.bid',
        string='Select Winner',
        required=True,
        domain="[('rfq_id', '=', rfq_id), ('state', '=', 'submitted')]",
    )

    @api.depends('rfq_id')
    def _compute_bid_ids(self):
        # Compute submitted bids for the RFQ and assign them to bid_ids
        for wizard in self:
            wizard.bid_ids = wizard.rfq_id.bid_ids.filtered(
                lambda b: b.state == 'submitted'
            )

    def action_confirm_winner(self):
        """Confirm the selected winner and trigger PO creation."""
        self.ensure_one()  # Ensure only one record is processed
        if not self.winning_bid_id:
            # Raise an error if no winning bid is selected
            raise UserError(_('Please select a winning bid before confirming.'))
        # Mark the selected bid as the winner
        self.winning_bid_id.action_mark_winner()
        # Close the wizard window
        return {'type': 'ir.actions.act_window_close'}
