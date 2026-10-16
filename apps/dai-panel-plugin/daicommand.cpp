// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
#include "daicommand.h"

#include <QDir>
#include <QKeyEvent>
#include <QLocale>
#include <QLocalSocket>
#include <QProcess>
#include <QStandardPaths>

namespace {

bool hebrewUi()
{
    const QString lang = qEnvironmentVariable("LC_ALL", qEnvironmentVariable("LC_MESSAGES", qEnvironmentVariable("LANG")));
    return lang.startsWith(QLatin1String("he"));
}

QString socketPath()
{
    // Same path as dai_command.ui.socket_path(); the directory is 0700.
    const QString runtime = qEnvironmentVariable("XDG_RUNTIME_DIR");
    return QDir(runtime).filePath(QStringLiteral("dai-command.sock"));
}

} // namespace

DaiCommandField::DaiCommandField(QWidget *parent)
    : QLineEdit(parent)
{
    setObjectName(QStringLiteral("DaiCommandField"));
    setPlaceholderText(hebrewUi() ? QStringLiteral("הקלידו פקודה…") : QStringLiteral("Type a command…"));
    setAccessibleName(hebrewUi() ? QStringLiteral("שורת הפקודות של D.Ai") : QStringLiteral("D.Ai Command"));
    setToolTip(QStringLiteral("D.Ai Command (Super+Space)"));
    setClearButtonEnabled(false);
    setMinimumWidth(240);
    setMaximumWidth(320);
    connect(this, &QLineEdit::textEdited, this, [this](const QString &text) {
        if (!text.isEmpty())
            emit handOff(text);
    });
}

void DaiCommandField::keyPressEvent(QKeyEvent *event)
{
    if (event->key() == Qt::Key_Return || event->key() == Qt::Key_Enter) {
        emit handOff(text());
        return;
    }
    if (event->key() == Qt::Key_Escape) {
        clear();
        clearFocus();
        return;
    }
    QLineEdit::keyPressEvent(event);
}

DaiCommandPlugin::DaiCommandPlugin(const ILXQtPanelPluginStartupInfo &startupInfo)
    : QObject()
    , ILXQtPanelPlugin(startupInfo)
{
    connect(&mField, &DaiCommandField::handOff, this, &DaiCommandPlugin::openCommand);
}

void DaiCommandPlugin::realign()
{
    mField.setFixedHeight(qMax(24, panel()->iconSize() + 10));
}

void DaiCommandPlugin::openCommand(const QString &text)
{
    // Prefer the running instance (instant); otherwise start it with the text.
    QLocalSocket socket;
    socket.connectToServer(socketPath());
    if (socket.waitForConnected(200)) {
        socket.write(QByteArrayLiteral("query:") + text.toUtf8());
        socket.flush();
        socket.waitForBytesWritten(200);
        socket.disconnectFromServer();
    } else {
        QProcess::startDetached(QStringLiteral("dai-command"), {QStringLiteral("--query"), text});
    }
    mField.clear();
    mField.clearFocus();
}
