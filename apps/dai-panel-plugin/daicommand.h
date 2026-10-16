// D.Ai Command field for lxqt-panel: a text field next to Start.
// Typing hands the text to D.Ai Command (apps/dai-command), which shows the
// results and keeps the focus; all logic stays in one place.
#pragma once

#include <QLineEdit>
#include <QObject>

#include "ilxqtpanelplugin.h"

class DaiCommandField : public QLineEdit
{
    Q_OBJECT
public:
    explicit DaiCommandField(QWidget *parent = nullptr);

signals:
    void handOff(const QString &text);

protected:
    void keyPressEvent(QKeyEvent *event) override;
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

    DaiCommandField mField;
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
