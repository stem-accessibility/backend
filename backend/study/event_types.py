# Event Categories
SESSION = "session"
CREATION = "creation"
EDITOR = "editor"
VIEW = "view"
GENERATION = "generation"
EXPORT = "export"
PUBLISH = "publish"
DELETE = "delete"
ERROR = "error"


EVENT_TYPES = {
    # -------------------------
    # SESSION
    # -------------------------
    "Study_Started": SESSION,
    "Study_Ended": SESSION,
    "Session_Resumed": SESSION,
    "Flowchart_Opened": SESSION,
    "Flowchart_Created": SESSION,
    "Flowchart_Renamed": SESSION,
    "Flowchart_Deleted": DELETE,

    # -------------------------
    # CREATION / INPUT MODE
    # -------------------------
    "Create_Mermaid": CREATION,
    "Create_Scratch": CREATION,
    "Create_Image": CREATION,
    "Upload_Image": CREATION,
    "Upload_Mermaid": CREATION,
    "Switch_Editor_Mode": CREATION,

    # -------------------------
    # EDITOR
    # -------------------------
    "Editor_Opened": EDITOR,
    "Node_Added": EDITOR,
    "Node_Deleted": EDITOR,
    "Node_Moved": EDITOR,
    "Node_Shape_Changed": EDITOR,
    "Node_Label_Edited": EDITOR,
    "Edge_Added": EDITOR,
    "Edge_Deleted": EDITOR,
    "Edge_Label_Edited": EDITOR,
    "Edge_Reconnected": EDITOR,
    "Edge_Style_Changed": EDITOR,
    "Undo_Clicked": EDITOR,
    "Redo_Clicked": EDITOR,

    # -------------------------
    # VIEW / REPRESENTATION USE
    # -------------------------
    "Summary_Viewed": VIEW,
    "Table_Viewed": VIEW,
    "Navigable_View_Viewed": VIEW,
    "Tactile_View_Viewed": VIEW,
    "Short_Alt_Viewed": VIEW,
    "Long_Description_Viewed": VIEW,
    "Representation_Switched": VIEW,
    "Summary_Edited": VIEW,
    "Short_Alt_Edited": VIEW,
    "Long_Description_Edited": VIEW,

    # -------------------------
    # AI / GENERATION
    # -------------------------
    "Generate_Outline_Clicked": GENERATION,
    "Generate_Summary_Clicked": GENERATION,
    "Regenerate_Summary_Clicked": GENERATION,
    "AI_Assist_Opened": GENERATION,
    "AI_Assist_Used": GENERATION,
    "Generation_Succeeded": GENERATION,
    "Generation_Failed": GENERATION,

    # -------------------------
    # SAVE / EXPORT
    # -------------------------
    "Save_Clicked": EXPORT,
    "Save_Succeeded": EXPORT,
    "Save_Failed": EXPORT,
    "Preview_Clicked": EXPORT,
    "Export_Clicked": EXPORT,
    "Export_Succeeded": EXPORT,
    "Export_Failed": EXPORT,

    # -------------------------
    # PUBLISH
    # -------------------------
    "Publish_Clicked": PUBLISH,
    "Publish_Succeeded": PUBLISH,
    "Publish_Failed": PUBLISH,
    "Unpublish_Clicked": PUBLISH,
    "Unpublish_Succeeded": PUBLISH,
    "Unpublish_Failed": PUBLISH,

    # -------------------------
    # DELETE
    # -------------------------
    "Delete_Clicked": DELETE,
    "Delete_Confirmed": DELETE,
    "Delete_Cancelled": DELETE,
    "Delete_Succeeded": DELETE,

    # -------------------------
    # ERRORS / FRICTION
    # -------------------------
    "Validation_Error": ERROR,
    "Upload_Failed": ERROR,
    "Image_Processing_Failed": ERROR,
    "Mermaid_Parse_Failed": ERROR,
    "Editor_Error": ERROR,
    "Publish_Error": ERROR,
}