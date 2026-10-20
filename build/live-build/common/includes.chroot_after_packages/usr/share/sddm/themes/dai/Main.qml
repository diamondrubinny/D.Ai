// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
// The D.Ai OS login screen (docs/V2.md D2). QtQuick and SddmComponents only: both come with sddm itself.
// The words come from SddmComponents' TextConstants, which sddm translates (Hebrew, Arabic, Russian...).
import QtQuick
import SddmComponents 2.0

Rectangle {
    id: root
    width: 1280
    height: 800
    color: "#0B1020"

    readonly property color surface: "#1C2547"
    readonly property color border: "#2A3563"
    readonly property color text: "#E6E9F5"
    readonly property color muted: "#A9B1D3"
    readonly property color accent: "#7C5CFF"
    readonly property color accentStrong: "#5B3FD6"
    readonly property color focusRing: "#22D3EE"
    readonly property color danger: "#F87171"
    readonly property real unit: Math.max(1, Math.min(width / 1280, height / 800))
    readonly property bool rtl: Qt.locale().textDirection === Qt.RightToLeft

    property int userIndex: Math.max(0, userModel.lastIndex)
    property string userName: userModel.lastUser
    property string realName: ""
    property bool busy: false

    LayoutMirroring.enabled: rtl
    LayoutMirroring.childrenInherit: true

    TextConstants { id: words }

    function chooseUser(index) {
        if (userModel.count === 0)
            return
        userIndex = (index + userModel.count) % userModel.count
        var item = users.itemAt(userIndex)
        if (item) {
            userName = item.login
            realName = item.display
        }
        password.text = ""
        password.forceActiveFocus()
    }

    function logIn() {
        var name = userModel.count > 0 ? userName : manualUser.text
        if (name.length === 0) {
            message.text = words.promptUser
            return
        }
        if (password.text.length === 0) {
            message.text = words.emptyPassword
            return
        }
        busy = true
        message.text = ""
        sddm.login(name, password.text, sessionModel.lastIndex)
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            root.busy = false
            password.text = ""
            message.text = words.loginFailed
            password.forceActiveFocus()
        }
        function onLoginSucceeded() {
            message.text = ""
        }
        function onInformationMessage(note) {
            message.text = note
        }
    }

    // The users, read once from sddm's model (a Repeater keeps their names at hand).
    Item {
        visible: false
        Repeater {
            id: users
            model: userModel
            delegate: Item {
                property string login: model.name
                property string display: model.realName && model.realName.length ? model.realName : model.name
            }
        }
    }

    Image {
        id: wallpaper
        anchors.fill: parent
        source: config.background
        fillMode: Image.PreserveAspectCrop
        asynchronous: false
    }
    Rectangle {  // a veil so the words stay readable on any wallpaper
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#990B1020" }
            GradientStop { position: 0.55; color: "#B30B1020" }
            GradientStop { position: 1.0; color: "#E60B1020" }
        }
    }

    // Time and date, top corner (the start side).
    Column {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.margins: 40 * root.unit
        spacing: 2 * root.unit
        Text {
            id: clock
            color: root.text
            font.family: "Noto Sans"
            font.pixelSize: 64 * root.unit
            font.weight: Font.Light
            text: Qt.formatTime(new Date(), Qt.locale().timeFormat(Locale.ShortFormat))
            Accessible.role: Accessible.StaticText
            Accessible.name: text
        }
        Text {
            id: date
            color: root.muted
            font.family: "Noto Sans"
            font.pixelSize: 20 * root.unit
            text: Qt.locale().toString(new Date(), "dddd, d MMMM")
        }
        Timer {
            interval: 10000
            running: true
            repeat: true
            onTriggered: {
                clock.text = Qt.formatTime(new Date(), Qt.locale().timeFormat(Locale.ShortFormat))
                date.text = Qt.locale().toString(new Date(), "dddd, d MMMM")
            }
        }
    }

    // The card in the middle: who, password, log in.
    Rectangle {
        id: card
        width: Math.min(440 * root.unit, root.width - 40)
        height: content.height + 56 * root.unit
        anchors.centerIn: parent
        radius: 22 * root.unit
        color: "#E6141B33"
        border.color: "#807C5CFF"
        border.width: 1

        Column {
            id: content
            anchors.centerIn: parent
            width: parent.width - 56 * root.unit
            spacing: 14 * root.unit

            Image {
                anchors.horizontalCenter: parent.horizontalCenter
                source: config.logo
                width: 84 * root.unit
                height: width
                sourceSize.width: width * 2
                sourceSize.height: height * 2
                fillMode: Image.PreserveAspectFit
                Accessible.ignored: true
            }

            // The user: a name with arrows when there are several, a field when sddm lists nobody.
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 10 * root.unit
                visible: userModel.count > 0
                RoundButton {
                    visible: userModel.count > 1
                    glyph: root.rtl ? "›" : "‹"
                    label: words.promptSelectUser
                    onClicked: root.chooseUser(root.userIndex - 1)
                }
                Text {
                    id: who
                    width: Math.min(implicitWidth, content.width - 120 * root.unit)
                    anchors.verticalCenter: parent.verticalCenter
                    color: root.text
                    elide: Text.ElideRight
                    font.family: "Noto Sans"
                    font.pixelSize: 26 * root.unit
                    font.weight: Font.Bold
                    text: root.realName.length ? root.realName : root.userName
                    Accessible.role: Accessible.StaticText
                    Accessible.name: words.userName + ": " + text
                }
                RoundButton {
                    visible: userModel.count > 1
                    glyph: root.rtl ? "‹" : "›"
                    label: words.promptSelectUser
                    onClicked: root.chooseUser(root.userIndex + 1)
                }
            }
            Field {
                id: manualUser
                visible: userModel.count === 0
                width: parent.width
                placeholder: words.userName
                KeyNavigation.tab: password
            }

            Field {
                id: password
                width: parent.width
                secret: true
                placeholder: words.password
                focus: true
                onAccepted: root.logIn()
                KeyNavigation.tab: loginButton
            }

            Text {
                id: capsWarning
                width: parent.width
                visible: keyboard.capsLock
                color: "#FBBF24"
                font.family: "Noto Sans"
                font.pixelSize: 14 * root.unit
                horizontalAlignment: Text.AlignHCenter
                text: "⇪ " + words.capslockWarning
                Accessible.role: Accessible.AlertMessage
                Accessible.name: words.capslockWarning
            }

            Rectangle {
                id: loginButton
                width: parent.width
                height: 50 * root.unit
                radius: 14 * root.unit
                activeFocusOnTab: true
                opacity: root.busy ? 0.7 : 1
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: root.accentStrong }
                    GradientStop { position: 1.0; color: "#2F6BD0" }
                }
                border.color: activeFocus ? root.focusRing : "transparent"
                border.width: 3
                Text {
                    anchors.centerIn: parent
                    color: "#FFFFFF"
                    font.family: "Noto Sans"
                    font.pixelSize: 18 * root.unit
                    font.weight: Font.Bold
                    text: root.busy ? "…" : words.login
                }
                Accessible.role: Accessible.Button
                Accessible.name: words.login
                Accessible.onPressAction: root.logIn()
                Keys.onReturnPressed: root.logIn()
                Keys.onEnterPressed: root.logIn()
                Keys.onSpacePressed: root.logIn()
                KeyNavigation.tab: layoutButton
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.logIn()
                }
            }

            Text {
                id: message
                width: parent.width
                color: root.danger
                font.family: "Noto Sans"
                font.pixelSize: 15 * root.unit
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                visible: text.length > 0
                Accessible.role: Accessible.AlertMessage
                Accessible.name: text
            }
        }
    }

    // Bottom bar: keyboard layout, then sleep, restart and shut down.
    Row {
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottomMargin: 32 * root.unit
        spacing: 14 * root.unit

        PillButton {
            id: layoutButton
            visible: keyboard.layouts.length > 1
            glyph: "⌨"
            caption: keyboard.layouts.length > 0 ? keyboard.layouts[keyboard.currentLayout].shortName.toUpperCase() : ""
            label: words.layout + ": " + caption
            onClicked: keyboard.currentLayout = (keyboard.currentLayout + 1) % keyboard.layouts.length
            KeyNavigation.tab: suspendButton
        }
        PillButton {
            id: suspendButton
            visible: sddm.canSuspend
            glyph: "☾"
            caption: words.suspend
            label: words.suspend
            onClicked: sddm.suspend()
            KeyNavigation.tab: rebootButton
        }
        PillButton {
            id: rebootButton
            visible: sddm.canReboot
            glyph: "↻"
            caption: words.reboot
            label: words.reboot
            onClicked: sddm.reboot()
            KeyNavigation.tab: powerButton
        }
        PillButton {
            id: powerButton
            visible: sddm.canPowerOff
            glyph: "⏻"
            caption: words.shutdown
            label: words.shutdown
            onClicked: sddm.powerOff()
            KeyNavigation.tab: password
        }
    }

    Text {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 16 * root.unit
        color: "#8C95BC"
        font.family: "Noto Sans"
        font.pixelSize: 12 * root.unit
        text: "D.Ai OS"
        Accessible.ignored: true
    }

    Component.onCompleted: {
        chooseUser(userIndex)
        if (userModel.count === 0)
            manualUser.forceActiveFocus()
    }

    // --- small controls, drawn here so the theme needs no extra QML modules ---

    component Field: FocusScope {
        id: field
        property alias text: input.text
        property string placeholder: ""
        property bool secret: false
        property bool shown: false
        signal accepted()
        height: 50 * root.unit
        Rectangle {
            anchors.fill: parent
            radius: 14 * root.unit
            color: root.surface
            border.color: input.activeFocus ? root.focusRing : root.border
            border.width: input.activeFocus ? 2 : 1
        }
        TextInput {
            id: input
            anchors.fill: parent
            anchors.leftMargin: 16 * root.unit
            anchors.rightMargin: (field.secret ? 50 : 16) * root.unit
            verticalAlignment: TextInput.AlignVCenter
            color: root.text
            selectionColor: root.accentStrong
            font.family: "Noto Sans"
            font.pixelSize: 17 * root.unit
            echoMode: field.secret && !field.shown ? TextInput.Password : TextInput.Normal
            passwordCharacter: "●"
            clip: true
            focus: true
            onAccepted: field.accepted()
            Accessible.role: Accessible.EditableText
            Accessible.name: field.placeholder
            Accessible.passwordEdit: field.secret
            Keys.onEscapePressed: text = ""
        }
        Text {
            anchors.fill: input
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: Text.AlignLeft
            color: "#8C95BC"
            font: input.font
            text: field.placeholder
            visible: input.text.length === 0
            Accessible.ignored: true
        }
        Rectangle {  // show / hide the password
            visible: field.secret
            width: 44 * root.unit  // a finger target (WCAG 2.5.5, docs/MOBILE.md A1)
            height: width
            radius: width / 2
            anchors.right: parent.right
            anchors.rightMargin: 8 * root.unit
            anchors.verticalCenter: parent.verticalCenter
            color: eye.containsMouse || activeFocus ? "#2A3563" : "transparent"
            border.color: activeFocus ? root.focusRing : "transparent"
            border.width: 2
            activeFocusOnTab: true
            Text {
                anchors.centerIn: parent
                color: root.muted
                font.pixelSize: 18 * root.unit
                text: field.shown ? "◉" : "◎"
            }
            Accessible.role: Accessible.Button
            Accessible.name: field.shown ? words.hidePasswordPrompt : words.showPasswordPrompt
            Accessible.onPressAction: field.shown = !field.shown
            Keys.onSpacePressed: field.shown = !field.shown
            MouseArea {
                id: eye
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: field.shown = !field.shown
            }
        }
    }

    component RoundButton: Rectangle {
        id: round
        property string glyph: ""
        property string label: ""
        signal clicked()
        width: 44 * root.unit  // a finger target (WCAG 2.5.5)
        height: width
        radius: width / 2
        color: area.containsMouse || activeFocus ? root.surface : "transparent"
        border.color: activeFocus ? root.focusRing : root.border
        border.width: activeFocus ? 2 : 1
        activeFocusOnTab: true
        anchors.verticalCenter: parent ? parent.verticalCenter : undefined
        Text { anchors.centerIn: parent; color: root.text; font.pixelSize: 20 * root.unit; text: round.glyph }
        Accessible.role: Accessible.Button
        Accessible.name: label
        Accessible.onPressAction: round.clicked()
        Keys.onSpacePressed: round.clicked()
        Keys.onReturnPressed: round.clicked()
        MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; onClicked: round.clicked() }
    }

    component PillButton: Rectangle {
        id: pill
        property string glyph: ""
        property string caption: ""
        property string label: ""
        signal clicked()
        height: 44 * root.unit  // a finger target (WCAG 2.5.5)
        width: row.width + 30 * root.unit
        radius: height / 2
        color: area.containsMouse || activeFocus ? "#E61C2547" : "#B3141B33"
        border.color: activeFocus ? root.focusRing : root.border
        border.width: activeFocus ? 2 : 1
        activeFocusOnTab: true
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 8 * root.unit
            Text { color: root.text; font.pixelSize: 17 * root.unit; text: pill.glyph }
            Text { color: root.text; font.family: "Noto Sans"; font.pixelSize: 15 * root.unit; text: pill.caption }
        }
        Accessible.role: Accessible.Button
        Accessible.name: label
        Accessible.onPressAction: pill.clicked()
        Keys.onSpacePressed: pill.clicked()
        Keys.onReturnPressed: pill.clicked()
        MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: pill.clicked() }
    }
}
