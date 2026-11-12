import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Pango from 'gi://Pango';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {historyLine, view} from './model.js';

const BAR_WIDTH = 48;

function textRow(text, styleClass = 'shaders-detail') {
    const item = new PopupMenu.PopupMenuSection();
    item.actor.add_style_class_name('shaders-row');
    const label = new St.Label({text, style_class: styleClass, x_expand: true});
    label.clutter_text.line_wrap = true;
    label.clutter_text.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
    label.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
    item.actor.add_child(label);
    return item;
}

export default class SteamShadersExtension extends Extension {
    enable() {
        this._alive = true;
        this._loading = false;
        this._lastMenu = '';
        this._cancellable = new Gio.Cancellable();
        this._statusFile = Gio.File.new_for_path(GLib.build_filenamev([
            GLib.get_user_data_dir(), 'steamcompshaderui', 'status.json',
        ]));
        this._indicator = new PanelMenu.Button(0.0, 'Compilação de shaders da Steam', false);
        const box = new St.BoxLayout({style_class: 'panel-status-menu-box shaders-panel'});
        box.add_child(new St.Icon({
            gicon: new Gio.FileIcon({file: this.dir.get_child('icons/shader-symbolic.svg')}),
            style_class: 'system-status-icon',
        }));
        this._track = new St.Widget({
            style_class: 'shaders-track', width: BAR_WIDTH, height: 4,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._fill = new St.Widget({style_class: 'shaders-fill', height: 4, width: 0});
        this._track.add_child(this._fill);
        box.add_child(this._track);
        this._label = new St.Label({
            text: '…', y_align: Clutter.ActorAlign.CENTER, style_class: 'shaders-percent',
        });
        box.add_child(this._label);
        this._indicator.add_child(box);
        this._indicator.menu.box.add_style_class_name('shaders-menu');
        this._indicator.hide();
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');
        this._indicator.menu.connect('open-state-changed', (_menu, open) => {
            if (open)
                this._refresh();
        });
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 2, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
        this._refresh();
    }

    _refresh() {
        if (!this._alive || this._loading)
            return;
        this._loading = true;
        const cancellable = this._cancellable;
        this._statusFile.load_contents_async(cancellable, (file, result) => {
            if (!this._alive || cancellable !== this._cancellable)
                return;
            this._loading = false;
            try {
                const [, contents] = file.load_contents_finish(result);
                this._paint(view(JSON.parse(new TextDecoder().decode(contents))));
            } catch (error) {
                this._paint({visible: false});
                // Ausência do serviço e cancelamento são estados normais.
                if (!error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND) &&
                    !error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED) && !this._readError) {
                    console.warn(`Steam Shaders: ${error.message}`);
                    this._readError = true;
                }
            }
        });
    }

    _paint(data) {
        if (!data.visible) {
            this._indicator.menu.close();
            this._indicator.hide();
            return;
        }
        this._readError = false;
        this._label.text = data.label;
        this._indicator.accessible_name = `${data.name}: ${data.detail}`;
        this._track.visible = data.percent !== null;
        this._fill.width = Math.round(BAR_WIDTH * (data.percent ?? 0) / 100);
        this._fill.visible = data.percent > 0;
        this._indicator.show();
        const key = JSON.stringify(data);
        if (key === this._lastMenu)
            return;
        this._lastMenu = key;
        const menu = this._indicator.menu;
        menu.removeAll();
        menu.addMenuItem(textRow(data.name, 'shaders-title'));
        menu.addMenuItem(textRow(data.detail));
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        for (const row of data.rows)
            menu.addMenuItem(textRow(row));
        if (data.recent.length) {
            menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem('Últimos processamentos'));
            for (const row of data.recent)
                menu.addMenuItem(textRow(historyLine(row), 'shaders-history'));
        }
    }

    disable() {
        this._alive = false;
        this._cancellable?.cancel();
        if (this._timer)
            GLib.source_remove(this._timer);
        this._timer = 0;
        this._indicator?.destroy();
        this._indicator = null;
        this._cancellable = null;
        this._statusFile = null;
    }
}
