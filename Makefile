ME = $(shell pwd | sed -e 's/\//\\\//g')

install:
	@echo "Installing .desktop file in "$(HOME)"/.local/share/applications/gnome-development-monitor.desktop"
	@cat gnome-development-monitor.desktop | sed -e "s/Exec=/Exec=$(ME)\//g" -e 's/Icon=gnome/Icon=$(ME)\/gnome.svg/g' > $(HOME)/.local/share/applications/gnome-development-monitor.desktop

uninstall:
	@echo "Removing .desktop file from "$(HOME)"/.local/share/applications/gnome-development-monitor.desktop"
	@rm -f $(HOME)/.local/share/applications/gnome-development-monitor.desktop
