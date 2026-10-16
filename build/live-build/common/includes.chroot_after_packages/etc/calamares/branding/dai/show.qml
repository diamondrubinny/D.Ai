// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
// Slides shown while D.Ai OS installs (Calamares slideshow API 2).
import QtQuick 2.0
import calamares.slideshow 1.0

Presentation {
    id: presentation

    Timer {
        interval: 7000
        running: presentation.activatedInCalamares
        repeat: true
        onTriggered: presentation.goToNextSlide()
    }

    Rectangle {
        anchors.fill: parent
        z: -1
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#0B1020" }
            GradientStop { position: 1.0; color: "#141B33" }
        }
    }

    component DaiSlide: Slide {
        property string heading: ""
        property string body: ""
        Image {
            id: logo
            source: "logo.svg"
            width: 96; height: 96
            sourceSize.width: 192; sourceSize.height: 192
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: 30
        }
        Text {
            id: title
            text: heading
            color: "#FFFFFF"
            font.pixelSize: 28
            font.bold: true
            anchors.top: logo.bottom
            anchors.topMargin: 20
            anchors.horizontalCenter: parent.horizontalCenter
        }
        Text {
            text: body
            color: "#C9CEE6"
            font.pixelSize: 17
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            width: parent.width * 0.8
            anchors.top: title.bottom
            anchors.topMargin: 16
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }

    DaiSlide {
        heading: "ברוכים הבאים ל־D.Ai OS"
        body: "מערכת הפעלה קלה, מאובטחת וקוד פתוח, עם AI שרץ כולו במחשב שלכם.\nWelcome to D.Ai OS — light, secure, open source, with AI that runs on your computer."
    }
    DaiSlide {
        heading: "🔒 המידע שלכם נשאר שלכם"
        body: "אם סימנתם \"הצפנת מערכת\", כל הדיסק מוצפן (LUKS). בלי הסיסמה אי אפשר לקרוא אותו, גם אם המחשב נגנב.\nWith \"Encrypt system\" the whole disk is encrypted (LUKS)."
    }
    DaiSlide {
        heading: "💎 התחל ושורת הפקודות"
        body: "היהלום הוא כפתור ההתחלה. לידו כותבים: אפליקציה, חישוב, ‎?שאלה ל־AI, ‎!התאמת מערכת, ‎+הוספה או בנייה.\nThe diamond is Start; type next to it: ? ask · ! tune · + build."
    }
    DaiSlide {
        heading: "🎙 מדברים במקום להקליד"
        body: "Super+H להכתבה בכל אפליקציה, Super+Shift+Space לפקודה קולית. התמלול מקומי, וההקלטה נמחקת מיד.\nSpeech is transcribed locally and deleted right away."
    }
    DaiSlide {
        heading: "✦ D.Ai Forge"
        body: "Super+B: מבקשים יכולת או אפליקציה (אנטי וירוס, סנכרון, אפליקציה משלכם), בודקים את התוכנית, והמערכת בונה. כל שינוי ניתן לביטול.\nAsk, review, and the system builds it — every change can be undone."
    }

    function onActivate() { presentation.currentSlide = 0 }
    function onLeave() { }
}
