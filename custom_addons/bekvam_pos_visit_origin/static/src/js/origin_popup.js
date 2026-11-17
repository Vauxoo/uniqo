odoo.define('bekvam_pos_visit_origin.OriginPopup', function (require) {
    'use strict';
    const AbstractAwaitablePopup = require('point_of_sale.AbstractAwaitablePopup');
    const Registries = require('point_of_sale.Registries');
    const policy = require('bekvam_pos_visit_origin.policy');
    const {useState} = owl;
    class BekvamOriginPopup extends AbstractAwaitablePopup {
        setup() {
            super.setup();
            this.state = useState({visit: this.props.visit || '', channel: this.props.channel || '', error: ''});
        }
        onVisitChange(event) {
            const visit = event.target.value;
            if (visit !== this.state.visit) this.state.channel = '';
            this.state.visit = visit;
            this.state.error = '';
        }
        onChannelChange(event) {
            this.state.channel = event.target.value;
            this.state.error = '';
        }
        getPayload() {
            return {visit: this.state.visit, channel: this.state.visit === 'first_visit' ? this.state.channel : ''};
        }
        async confirm() {
            this.state.error = policy.error(this.state.visit, this.state.channel);
            if (this.state.error) return;
            return super.confirm();
        }
    }
    BekvamOriginPopup.template = 'BekvamOriginPopup';
    Registries.Component.add(BekvamOriginPopup);
    return BekvamOriginPopup;
});
