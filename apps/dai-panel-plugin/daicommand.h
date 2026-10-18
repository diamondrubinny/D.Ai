// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
// D.Ai Command field for lxqt-panel: a text field next to Start.
// Typing hands the text to D.Ai Command (apps/dai-command), which shows the
// results and keeps the focus; all logic stays in one place.
// The smart field (docs/TASKBAR.md §2.2) adds an idea chip when D.Ai Evolve
// has a suggestion, a microphone for D.Ai Voice, and hints in the empty field,
// each shown once per login and changed slowly.
#pragma once

#include <QFileSystemWatcher>
#include <QLineEdit>
#include <QObject>
#include <QStringList>
#include <QTimer>
#include <functional>

#include "ilxqtpanelplugin.h"

class QAction;

class DaiCommandField : public QLineEdit
{
    Q_OBJECT
public:
    // speak starts D.Ai Voice (replaced in tests).
    explicit DaiCommandField(std::function<bool()> speak = {}, QWidget *parent = nullptr);

    // How many ideas D.Ai Evolve has (from status.json); 0 hides the chip.
    void setIdeas(int ideas);
    int ideas() const { return mIdeas; }
    bool ideaShown() const;
    void dismissIdea();
    // The next hint in the empty field; after one round the plain placeholder stays.
    void nextHint();
    QStringList hints() const { return mHints; }

    static int ideasFromJson(const QByteArray &data);

signals:
    void handOff(const QString &text);

protected:
    void keyPressEvent(QKeyEvent *event) override;
    void focusInEvent(QFocusEvent *event) override;

private:
    void updateIdea();

    std::function<bool()> mSpeak;
    QAction *mIdea = nullptr;
    QAction *mMic = nullptr;
    int mIdeas = 0;
    int mDismissed = 0;
    QStringList mHints;
    int mHint = -1;
    QString mPlaceholder;
    QTimer mHintTimer;
};

class DaiCommandPlugin : public QObject, public ILXQtPanelPlugin
{
    Q_OBJECT
public:
    explicit DaiCommandPlugin(const ILXQtPanelPluginStartupInfo &startupInfo);

    QWidget *widget() override { return &mField; }
    QString themeId() const override { return QStringLiteral("DaiCommand"); }
    ILXQtPanelPlugin::Flags flags() const override { return SingleInstance; }
    void realign() override;

private:
    void openCommand(const QString &text);
    void reloadStatus();

    DaiCommandField mField;
    QFileSystemWatcher mWatcher;
    QTimer mSettle;
    QString mDirectory;
};

class DaiCommandLibrary : public QObject, public ILXQtPanelPluginLibrary
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "lxqt.org/Panel/PluginInterface/3.0")
    Q_INTERFACES(ILXQtPanelPluginLibrary)
public:
    ILXQtPanelPlugin *instance(const ILXQtPanelPluginStartupInfo &startupInfo) const override
    {
        return new DaiCommandPlugin(startupInfo);
    }
};
