# Requirements: Smart Message Length Handling

## Introduction

This specification defines a message display system for the IRIS chat interface that truncates long messages at 150 characters and provides document view/download for messages exceeding 300 characters. The system is content-type aware, detecting Markdown, email, video, and picture content to provide appropriate handling.

## Critical Constraints
- ChatWing: 255px width, 50vh height - limited viewport requires careful space management
- Work within existing Message interface and chat-view.tsx structure
- Maintain existing message styling (sender indicators, timestamps, feedback action bars)
- NO new component files unless absolutely necessary - inline implementation in chat-view.tsx
- Backend integration must use existing WebSocket patterns

## Requirements

### Requirement 1: Message Length Thresholds

**User Story:** As a user, I want messages to be truncated after 150 characters and offered as downloadable documents after 300 characters, so that the chat interface remains clean and readable.

#### Acceptance Criteria

1. WHEN a message exceeds 150 characters THEN THE SYSTEM SHALL display only the first 150 characters with an ellipsis

2. WHEN a message exceeds 300 characters THEN THE SYSTEM SHALL treat it as a document with download/view options

3. THE SYSTEM SHALL display a "Show more" button for truncated messages (150-300 chars) that expands inline

4. THE SYSTEM SHALL display a document icon with "View full document" button for messages >300 chars

5. THE SYSTEM SHALL count characters using JavaScript's `String.length` property

### Requirement 2: Content Type Detection

**User Story:** As a user, I want the system to detect what type of content a message contains, so that it can be displayed appropriately with relevant icons and actions.

#### Acceptance Criteria

1. THE SYSTEM SHALL detect the following content types:
   - **Markdown**: Content containing Markdown syntax (headers, lists, code blocks, links)
   - **Email**: Content with email-like structure (From:, To:, Subject: headers or @domain.com patterns)
   - **Video**: Content containing video URLs (YouTube, Vimeo, or direct video file links)
   - **Picture**: Content containing image URLs (.jpg, .png, .gif, .webp, etc.)
   - **Text**: Default type when no specific pattern matches

2. WHEN content type is detected THEN THE SYSTEM SHALL display an appropriate icon:
   - Markdown: FileText icon
   - Email: Mail icon
   - Video: Video icon
   - Picture: Image icon
   - Text: File icon

3. THE SYSTEM SHALL prioritize content type detection in order: Video > Picture > Markdown > Email > Text

4. IF a message contains multiple content types THEN THE SYSTEM SHALL use the first detected type

### Requirement 3: Truncated Message Display (151-300 chars)

**User Story:** As a user, I want moderately long messages to show a preview with an option to expand inline, so that I can quickly scan content while having access to the full message when needed.

#### Acceptance Criteria

1. WHEN a message is 151-300 characters THEN THE SYSTEM SHALL:
   - Display the first 150 characters
   - Show a fade-out gradient at the truncation point
   - Display a content type icon
   - Show a "Show more" button below the text

2. WHEN the user clicks "Show more" THEN THE SYSTEM SHALL expand the message to display its full content inline

3. WHEN expanded THEN THE SYSTEM SHALL show a "Show less" button to collapse back

4. THE SYSTEM SHALL maintain the expanded/collapsed state per message during the session

5. THE SYSTEM SHALL animate the expand/collapse with Framer Motion (respecting prefers-reduced-motion)

6. THE SYSTEM SHALL display share and download icons in the expanded view

### Requirement 4: Document Mode (>300 chars)

**User Story:** As a user, I want very long messages to be treated as documents with download and view options, so that they don't clutter the chat and can be read in a proper viewing environment.

#### Acceptance Criteria

1. WHEN a message exceeds 300 characters THEN THE SYSTEM SHALL display:
   - First 150 characters as a preview
   - Content type icon (larger size)
   - Character count badge (e.g., "450 chars")
   - "View full document" button
   - Share icon button
   - Download icon button

2. WHEN the user clicks "View full document" THEN THE SYSTEM SHALL open a modal overlay with:
   - Full message content in a clean, readable format
   - Proper typography (14px font, 1.6 line-height, comfortable padding)
   - Content type indicator in header
   - Action bar with: Download, Share, Copy, Close
   - Scrollable content area

3. WHEN the user clicks "Download" THEN THE SYSTEM SHALL:
   - Trigger a .txt file download
   - Filename format: `IRIS_[ContentType]_[YYYYMMDD]_[HHMMSS].txt`
   - Content: Full message text with metadata header

4. WHEN the user clicks "Share" THEN THE SYSTEM SHALL copy the message content to clipboard and show a toast confirmation

5. THE SYSTEM SHALL display a warning badge if the message exceeds 1000 characters

### Requirement 5: Content-Specific Handling

**User Story:** As a user, I want different content types to be handled appropriately, so that Markdown renders properly, images/videos are recognizable, and emails are formatted correctly.

#### Acceptance Criteria

1. **Markdown Content:**
   - Render Markdown formatting in document view
   - Preserve code blocks with monospace font
   - Style headers, lists, and links appropriately

2. **Email Content:**
   - Preserve email header structure (From, To, Subject)
   - Format as plain text in document view
   - Highlight email addresses

3. **Video Content:**
   - Display video thumbnail if URL is embeddable
   - Show "Open video" link in preview
   - Provide direct URL in document view

4. **Picture Content:**
   - Show image thumbnail in preview if URL is direct image link
   - Provide full-size image view in document modal
   - Support common formats: jpg, png, gif, webp, svg

### Requirement 6: Accessibility

**User Story:** As a user with accessibility needs, I want all message actions to be keyboard accessible and screen reader friendly.

#### Acceptance Criteria

1. THE SYSTEM SHALL make all buttons keyboard accessible (Tab navigation, Enter/Space activation)

2. THE SYSTEM SHALL include appropriate ARIA labels:
   - `aria-expanded` on expand/collapse buttons
   - `aria-label` describing the action (e.g., "Show full message, 250 characters")
   - `role="dialog"` on the document view modal
   - `aria-modal="true"` on the modal when open

3. WHEN a modal is opened THEN THE SYSTEM SHALL trap focus within the modal

4. WHEN Escape key is pressed in the document view modal THEN THE SYSTEM SHALL close the modal

5. THE SYSTEM SHALL respect `prefers-reduced-motion` by disabling animations

### Requirement 7: Backend Integration

**User Story:** As a developer, I want the backend to support document generation for large messages, so that users can export conversations with proper formatting.

#### Acceptance Criteria

1. WHEN the frontend requests a document export via WebSocket message type `export_message` THEN THE SYSTEM SHALL generate a text document with metadata

2. THE SYSTEM SHALL include the following in exported documents:
   - Content type header
   - Timestamp and conversation context
   - Full message content
   - IRIS version

3. THE SYSTEM SHALL clean up temporary export files after 24 hours

4. THE SYSTEM SHALL limit export requests to 1 per 5 seconds per session

## Design Constraints

1. **Inline Implementation**: All changes made directly in chat-view.tsx
2. **Existing Patterns**: Use existing button styles, icons from lucide-react, and color variables (glowColor, fontColor)
3. **Minimal State**: Use useState for expanded message tracking, avoid complex state management
4. **Consistent Styling**: Match existing message separator, padding, and typography patterns
