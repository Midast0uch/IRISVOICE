#!/bin/bash
# Script to clean up unused UI components after dependency removal
# Run this after updating package.json and reinstalling dependencies

# Remove unused UI components (kept components listed below)
# KEPT: None - all @radix-ui dependencies removed
# All components in components/ui/ use @radix-ui packages that are now removed

echo "Removing unused UI components..."
echo "WARNING: All UI components use @radix-ui which has been removed from dependencies."
echo "If you need any of these components, you'll need to reinstall the specific @radix-ui package."

# List of components to remove (all use Radix UI)
UNUSED_COMPONENTS=(
  "accordion.tsx"
  "alert-dialog.tsx"
  "alert.tsx"
  "aspect-ratio.tsx"
  "avatar.tsx"
  "badge.tsx"
  "breadcrumb.tsx"
  "button-group.tsx"
  "button.tsx"
  "calendar.tsx"
  "card.tsx"
  "carousel.tsx"
  "chart.tsx"
  "checkbox.tsx"
  "collapsible.tsx"
  "command.tsx"
  "context-menu.tsx"
  "dialog.tsx"
  "drawer.tsx"
  "dropdown-menu.tsx"
  "empty.tsx"
  "field.tsx"
  "form.tsx"
  "hover-card.tsx"
  "input-group.tsx"
  "input-otp.tsx"
  "input.tsx"
  "item.tsx"
  "kbd.tsx"
  "label.tsx"
  "menubar.tsx"
  "navigation-menu.tsx"
  "pagination.tsx"
  "popover.tsx"
  "progress.tsx"
  "radio-group.tsx"
  "resizable.tsx"
  "scroll-area.tsx"
  "select.tsx"
  "separator.tsx"
  "sheet.tsx"
  "sidebar.tsx"
  "skeleton.tsx"
  "slider.tsx"
  "sonner.tsx"
  "spinner.tsx"
  "switch.tsx"
  "table.tsx"
  "tabs.tsx"
  "textarea.tsx"
  "toast.tsx"
  "toaster.tsx"
  "toggle-group.tsx"
  "toggle.tsx"
  "tooltip.tsx"
  "use-mobile.tsx"
  "use-toast.ts"
)

for component in "${UNUSED_COMPONENTS[@]}"; do
  echo "Would remove: components/ui/$component"
done

echo ""
echo "To actually remove these files, run:"
echo "  cd components/ui && rm -f ${UNUSED_COMPONENTS[*]}"
