"""Built-in capability class paths."""

BUILTIN_CAPABILITY_CLASSES: dict[str, str] = {
    "chat": "deeptutor.agents.chat.capability:ChatCapability",
    "visualize": "deeptutor.agents.visualize.capability:VisualizeCapability",
    "mastery_path": "deeptutor.capabilities.mastery.capability:MasteryPathCapability",
}
