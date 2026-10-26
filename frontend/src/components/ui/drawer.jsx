import { Drawer as DrawerPrimitive } from "vaul";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

function Drawer({
  shouldScaleBackground = false,
  direction = "right",
  ...props
}) {
  return (
    <DrawerPrimitive.Root
      data-slot="drawer"
      direction={direction}
      shouldScaleBackground={shouldScaleBackground}
      {...props}
    />
  );
}

function DrawerTrigger({ asChild = true, render, children, ...props }) {
  if (render) {
    return (
      <DrawerPrimitive.Trigger data-slot="drawer-trigger" asChild {...props}>
        {render}
      </DrawerPrimitive.Trigger>
    );
  }
  return (
    <DrawerPrimitive.Trigger data-slot="drawer-trigger" asChild={asChild} {...props}>
      {children}
    </DrawerPrimitive.Trigger>
  );
}

function DrawerPortal({ ...props }) {
  return <DrawerPrimitive.Portal data-slot="drawer-portal" {...props} />;
}

function DrawerClose({ asChild = true, render, children, ...props }) {
  if (render) {
    return (
      <DrawerPrimitive.Close data-slot="drawer-close" asChild {...props}>
        {render}
      </DrawerPrimitive.Close>
    );
  }
  return (
    <DrawerPrimitive.Close data-slot="drawer-close" asChild={asChild} {...props}>
      {children}
    </DrawerPrimitive.Close>
  );
}

function DrawerOverlay({ className, ...props }) {
  return (
    <DrawerPrimitive.Overlay
      data-slot="drawer-overlay"
      className={cn(
        "fixed inset-0 z-50 bg-black/40 backdrop-blur-xs transition-opacity duration-300 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
        className
      )}
      {...props}
    />
  );
}

function DrawerContent({ className, children, direction = "right", ...props }) {
  return (
    <DrawerPortal>
      <DrawerOverlay />
      <DrawerPrimitive.Content
        data-slot="drawer-content"
        className={cn(
          "fixed z-50 flex flex-col bg-card text-card-foreground shadow-2xl transition-transform duration-300 ease-out focus:outline-none",
          direction === "right" &&
            "inset-y-0 right-0 h-full w-full max-w-lg rounded-l-3xl border-l border-border",
          direction === "left" &&
            "inset-y-0 left-0 h-full w-full max-w-lg rounded-r-3xl border-r border-border",
          direction === "bottom" &&
            "inset-x-0 bottom-0 mt-24 h-auto max-h-[85vh] rounded-t-3xl border-t border-border",
          direction === "top" &&
            "inset-x-0 top-0 mb-24 h-auto max-h-[85vh] rounded-b-3xl border-b border-border",
          className
        )}
        {...props}
      >
        <DrawerPrimitive.Close className="absolute top-5 right-5 rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <X className="size-4" aria-hidden="true" />
          <span className="sr-only">Close</span>
        </DrawerPrimitive.Close>
        {children}
      </DrawerPrimitive.Content>
    </DrawerPortal>
  );
}

function DrawerHeader({ className, ...props }) {
  return (
    <div
      data-slot="drawer-header"
      className={cn("flex flex-col gap-1.5 p-6 border-b border-border/70 pr-12", className)}
      {...props}
    />
  );
}

function DrawerFooter({ className, ...props }) {
  return (
    <div
      data-slot="drawer-footer"
      className={cn("mt-auto flex items-center justify-end gap-3 p-6 border-t border-border/70 bg-muted/20", className)}
      {...props}
    />
  );
}

function DrawerTitle({ className, ...props }) {
  return (
    <DrawerPrimitive.Title
      data-slot="drawer-title"
      className={cn("font-display text-xl font-bold tracking-tight text-ink", className)}
      {...props}
    />
  );
}

function DrawerDescription({ className, ...props }) {
  return (
    <DrawerPrimitive.Description
      data-slot="drawer-description"
      className={cn("text-xs text-ink-soft leading-relaxed", className)}
      {...props}
    />
  );
}

export {
  Drawer,
  DrawerPortal,
  DrawerOverlay,
  DrawerTrigger,
  DrawerClose,
  DrawerContent,
  DrawerHeader,
  DrawerFooter,
  DrawerTitle,
  DrawerDescription,
};
