#!/usr/bin/env python3
"""Smart chunking for legal/grant documents — IMPROVED VERSION.

Merges headings with following content instead of keeping them separate.
"""

import re
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

@dataclass
class Chunk:
    text: str
    chunk_type: str  # 'section', 'body', 'list', 'table'
    section_path: List[str]
    level: int
    heading: Optional[str] = None  # The section heading this chunk belongs to


class SmartChunkerV2:
    """Improved chunker that merges headings with content."""
    
    HEADING_PATTERNS = [
        (r'^\s*(\d+)\.\s+([A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ][^.]+)$', 1),
        (r'^\s*(\d+)\.(\d+)\s+([A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ][^.]+)$', 2),
        (r'^\s*(\d+)\.(\d+)\.(\d+)\s+([A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ][^.]+)$', 3),
        (r'^\s*([a-z])\)\s+([A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ][^.]+)$', 2),
        (r'^\s*([IVX]+)\.\s+([A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ][^.]+)$', 1),
        (r'^\s*(§\s*\d+[^.]*$)', 1),
        # All-caps or Title Case lines (potential headings without numbers)
        (r'^\s*([A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ][A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ\s]+[A-ZÁÉÍÓÚÝŽŠČŘĎŤŇĽĹ])\s*$', 1),
    ]
    
    # Numbered list items (1., 2., 3., ...) - treated as sub-items, not section breaks
    LIST_ITEM_PATTERN = r'^\s*(\d+)\.\s+(.+)$'  # Number + any text (including lowercase)
    
    MAX_CHUNK_SIZE = 2500  # Max chars per chunk
    MIN_CHUNK_SIZE = 150   # Min chars (to avoid tiny chunks)
    
    def __init__(self):
        self.section_stack: List[Tuple[str, int]] = []
        self.current_heading: Optional[str] = None
    
    def _is_heading(self, line: str) -> Tuple[bool, int, str]:
        line = line.strip()
        if not line:
            return False, 0, ""
        for pattern, level in self.HEADING_PATTERNS:
            if re.match(pattern, line, re.IGNORECASE):
                return True, level, line
        return False, 0, line
    
    def _update_section_stack(self, heading: str, level: int):
        while self.section_stack and self.section_stack[-1][1] >= level:
            self.section_stack.pop()
        self.section_stack.append((heading, level))
    
    def _get_section_path(self) -> List[str]:
        return [h for h, _ in self.section_stack]
    
    def chunk(self, text: str) -> List[Chunk]:
        """
        Main chunking method.
        
        Key improvement: Headings are NOT separate chunks.
        They are prepended to the following content chunk.
        """
        lines = text.split('\n')
        chunks: List[Chunk] = []
        
        buffer: List[str] = []
        buffer_size = 0
        pending_heading: Optional[str] = None
        pending_level = 0
        current_type = "body"
        
        i = 0
        while i < len(lines):
            line = lines[i]
            is_heading, level, clean_line = self._is_heading(line)
            
            if is_heading:
                # Flush current buffer WITH the previous heading
                if buffer and buffer_size >= self.MIN_CHUNK_SIZE:
                    chunk_text = '\n'.join(buffer).strip()
                    if pending_heading and not chunk_text.startswith(pending_heading):
                        chunk_text = f"{pending_heading}\n{chunk_text}"
                    
                    chunks.append(Chunk(
                        text=chunk_text,
                        chunk_type=current_type,
                        section_path=self._get_section_path(),
                        level=pending_level if pending_heading else (self.section_stack[-1][1] if self.section_stack else 0),
                        heading=pending_heading
                    ))
                    buffer = []
                    buffer_size = 0
                
                # Update hierarchy
                self._update_section_stack(clean_line, level)
                pending_heading = clean_line
                pending_level = level
                current_type = "body"
                i += 1
                continue
            
            # Detect content type
            stripped = line.strip()
            if stripped.startswith(('•', '-', '*', '○', '▪', '')) or re.match(r'^\d+\.', stripped):
                current_type = "list"
            
            # Add to buffer
            buffer.append(line)
            buffer_size += len(line)
            
            # Check size limit
            if buffer_size >= self.MAX_CHUNK_SIZE:
                # Find good break point (paragraph boundary)
                # PROTECT NUMBERED LISTS: don't break between numbered items
                break_idx = len(buffer)
                in_numbered_list = False
                
                for j in range(len(buffer) - 1, max(0, len(buffer) - 20), -1):
                    line_text = buffer[j].strip()
                    # Check if this line starts a numbered item
                    if re.match(r'^\d+\.', line_text):
                        if in_numbered_list:
                            # Found previous item, don't break here
                            continue
                        else:
                            # Found the current item, mark that we're in a list
                            in_numbered_list = True
                            continue
                    # Good break point: empty line or end of sentence, NOT in middle of numbered list
                    if (line_text == '' or line_text.endswith('.')) and not re.match(r'^\d+\.', buffer[min(j+1, len(buffer)-1)].strip() if j+1 < len(buffer) else ''):
                        break_idx = j + 1
                        break
                
                chunk_text = '\n'.join(buffer[:break_idx]).strip()
                if pending_heading and not chunk_text.startswith(pending_heading):
                    chunk_text = f"{pending_heading}\n{chunk_text}"
                
                if len(chunk_text) >= self.MIN_CHUNK_SIZE:
                    chunks.append(Chunk(
                        text=chunk_text,
                        chunk_type=current_type,
                        section_path=self._get_section_path(),
                        level=pending_level if pending_heading else (self.section_stack[-1][1] if self.section_stack else 0),
                        heading=pending_heading
                    ))
                
                # Continue with rest
                buffer = buffer[break_idx:]
                buffer_size = sum(len(l) for l in buffer)
                # Don't reuse heading for continuation chunks
                pending_heading = None
                current_type = "body"
            
            i += 1
        
        # Flush final buffer
        if buffer and buffer_size >= self.MIN_CHUNK_SIZE:
            chunk_text = '\n'.join(buffer).strip()
            if pending_heading and not chunk_text.startswith(pending_heading):
                chunk_text = f"{pending_heading}\n{chunk_text}"
            
            chunks.append(Chunk(
                text=chunk_text,
                chunk_type=current_type,
                section_path=self._get_section_path(),
                level=pending_level if pending_heading else (self.section_stack[-1][1] if self.section_stack else 0),
                heading=pending_heading
            ))
        
        return chunks
    
    def chunk_with_context(self, text: str) -> List[Dict]:
        """Chunk and return enriched chunks."""
        chunks = self.chunk(text)
        result = []
        
        for i, chunk in enumerate(chunks):
            section_context = " > ".join(chunk.section_path[-2:]) if len(chunk.section_path) >= 2 else ""
            
            # First chunk in section gets full heading context
            enriched_text = chunk.text
            if chunk.heading and not chunk.text.startswith(chunk.heading):
                enriched_text = f"[{chunk.heading}]\n{chunk.text}"
            
            result.append({
                "text": enriched_text,
                "raw_text": chunk.text,
                "type": chunk.chunk_type,
                "section_path": chunk.section_path,
                "level": chunk.level,
                "heading": chunk.heading,
                "section_context": section_context,
            })
        
        return result


# For backward compatibility
SmartChunker = SmartChunkerV2


if __name__ == "__main__":
    # Test
    sample = """
1. VŠEOBECNÉ INFORMÁCIE
Fond poskytuje podporu formou Dotácie v zmysle Zákona o Fonde.
Táto Príručka je určená pre Žiadateľov.

2. PODMIENKY ŽIADANIA
2.1 Oprávnení žiadatelia
Žiadateľom môže byť právnická osoba alebo fyzická osoba.
Podmienkou je registrácia v Slovenskej republike.

2.2 Nevyhnutné náklady
Medzi oprávnené náklady patria:
• náklady na prípravu projektu
• náklady na realizáciu
• náklady na administráciu

3. PROCES HODNOTENIA
Žiadosti sa hodnotia podľa týchto kritérií:
a) Relevancia projektu
b) Kvalita predloženého riešenia
c) Udržateľnosť projektu
"""
    
    chunker = SmartChunkerV2()
    chunks = chunker.chunk_with_context(sample)
    
    print(f"Created {len(chunks)} chunks:")
    for i, c in enumerate(chunks):
        print(f"\n{i+1}. [{c['type']}] {' > '.join(c['section_path'][-2:]) if c['section_path'] else 'root'}")
        print(f"   {c['text'][:150]}...")
