// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
// The clock in the Diamond Bar (docs/TASKBAR.md §2.4): the time, the full date in
// its tooltip, and a click opens D.Ai Quick. LXQt's own clock cannot open
// anything else, so this small one replaces it. It wakes once a minute, on
// the minute.
#pragma once

#include <QObject>
#include <QTimer>
#include <QToolButton>
#include <functional>

#include "ilxqtpanelplugin.h"

class DaiClockButton : public QToolButton
{
    Q_OBJECT
public:
    // launch starts D.Ai Quick (replaced in tests).
    explicit DaiClockButton(std::function<bool()> launch = {}, QWidget *parent = nullptr);
    void refresh(const QDateTime &now);

private:
    void schedule();

    std::function<bool()> mLaunch;
    QTimer mTimer;
};

class DaiClockPlugin : public QObject, public ILXQtPanelPlugin
{
    Q_OBJECT
public:
    explicit DaiClockPlugin(const ILXQtPanelPluginStartupInfo &startupInfo);

    QWidget *widget() override { return &mButton; }
    QString themeId() const override { return QStringLiteral("DaiClock"); }
    ILXQtPanelPlugin::Flags flags() const override { return SingleInstance; }

private:
    DaiClockButton mButton;
};

class DaiClockLibrary : public QObject, public ILXQtPanelPluginLibrary
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "lxqt.org/Panel/PluginInterface/3.0")
    Q_INTERFACES(ILXQtPanelPluginLibrary)
public:
    ILXQtPanelPlugin *instance(const ILXQtPanelPluginStartupInfo &startupInfo) const override
    {
        return new DaiClockPlugin(startupInfo);
    }
};
