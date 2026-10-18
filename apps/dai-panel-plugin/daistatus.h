// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
// The Living Diamond (docs/TASKBAR.md §2.1): the Start button also shows, at a
// glance, whether something needs you - a red dot while an app records, an
// amber triangle when D.Ai Heal found a problem, a small cyan diamond when
// D.Ai Evolve has an idea. It decorates LXQt's own Start button (same
// process) instead of replacing it, so the menu and its shortcuts stay as
// they are. State comes from $XDG_RUNTIME_DIR/dai/status.json (dai_status),
// watched with inotify; nothing is polled.
#pragma once

#include <QFileSystemWatcher>
#include <QObject>
#include <QPointer>
#include <QStringList>
#include <QTimer>
#include <QToolButton>
#include <QWidget>

#include "ilxqtpanelplugin.h"

struct DaiStatus
{
    enum class Kind { None, Idea, Heal, Privacy };
    Kind kind = Kind::None;
    int heal = 0;
    int ideas = 0;
    QStringList recording;

    // The most important thing wins: privacy, then a problem, then an idea.
    static DaiStatus fromJson(const QByteArray &data);
    QString describe(bool hebrew) const;
};

class DaiStatusBadge : public QWidget
{
    Q_OBJECT
public:
    explicit DaiStatusBadge(QToolButton *start);
    void setStatus(const DaiStatus &status);

protected:
    void paintEvent(QPaintEvent *event) override;
    bool eventFilter(QObject *watched, QEvent *event) override;

private:
    DaiStatus mStatus;
};

class DaiStatusPlugin : public QObject, public ILXQtPanelPlugin
{
    Q_OBJECT
public:
    explicit DaiStatusPlugin(const ILXQtPanelPluginStartupInfo &startupInfo);

    QWidget *widget() override { return &mAnchor; }
    QString themeId() const override { return QStringLiteral("DaiStatus"); }
    ILXQtPanelPlugin::Flags flags() const override { return SingleInstance; }
    void realign() override;

private:
    void attach();
    void reload();

    QWidget mAnchor;
    QFileSystemWatcher mWatcher;
    QTimer mSettle;
    QPointer<QToolButton> mStart;
    QPointer<DaiStatusBadge> mBadge;
    QString mStartName;
    QString mStartTip;
    QString mDirectory;
};

class DaiStatusLibrary : public QObject, public ILXQtPanelPluginLibrary
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "lxqt.org/Panel/PluginInterface/3.0")
    Q_INTERFACES(ILXQtPanelPluginLibrary)
public:
    ILXQtPanelPlugin *instance(const ILXQtPanelPluginStartupInfo &startupInfo) const override
    {
        return new DaiStatusPlugin(startupInfo);
    }
};
