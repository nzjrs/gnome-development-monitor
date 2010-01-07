ME = $(shell pwd | sed -e 's/\//\\\//g')

install:
	@echo "Installing .desktop file in "$(HOME)"/.local/share/applications/gnome-commits-monitor.desktop"
	@cat gnome-commits-monitor.desktop | sed -e "s/Exec=/Exec=$(ME)\//g" -e 's/Icon=gnome/Icon=$(ME)\/gnome.svg/g' > $(HOME)/.local/share/applications/gnome-commits-monitor.desktop

uninstall:
	@echo "Removing .desktop file from "$(HOME)"/.local/share/applications/gnome-commits-monitor.desktop"
	@rm -f $(HOME)/.local/share/applications/gnome-commits-monitor.desktop
